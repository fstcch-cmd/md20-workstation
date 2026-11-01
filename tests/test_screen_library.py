"""HTS compound library: sheet parsing, download/resolve with a fake network, caching, honesty of the manifest.
Pure Python (RDKit absent → files are stored unchecked, exactly as the code promises)."""
import json

import pandas as pd
import pytest

from md20.docking.library import (read_library, resolve_library, write_template, fetch_with_retry, FetchError, RateLimiter,
                                  LibraryFilters, usable_entries, problem_entries, PUBCHEM, CHEMBL, RCSB_LIGAND)
from md20.util import DecisionLog

SDF = "\n  fake\n\n  1  0  0  0  0  0  0  0  0  0999 V2000\n    0.0000    0.0000    0.0000 C   0  0\nM  END\n$$$$\n"


@pytest.fixture(autouse=True)
def _pure_library_path(monkeypatch):
    """These tests pin the no-RDKit path (fake one-atom SDFs, honest `checked: False`).  In the openmm-stack env RDKit
    is installed and its size filters would skip every fake compound (CI c4b5de6, D-25); the RDKit path is covered by
    tests/test_screen_integration.py."""
    import md20.docking.library as lib
    monkeypatch.setattr(lib, "_rdkit_available", lambda: False)


# ----------------------------------------------------------------------------- sheet parsing
def test_read_csv_with_aliases(tmp_path):
    p = tmp_path / "lib.csv"
    p.write_text("Compound,SMILES,CID,InChIKey,ChEMBL ID,PDB ligand,File\n"
                 "benzamidine,NC(=[NH2+])c1ccccc1,,,,,\n"
                 "aspirin,,2244.0,,,,\n"
                 "ATP,,,,,ATP,\n", encoding="utf-8")
    entries, problems = read_library(p)
    assert not problems
    assert [e.name for e in entries] == ["benzamidine", "aspirin", "ATP"]
    assert entries[1].pubchem_cid == "2244"                 # Excel float artefact removed
    assert entries[0].identifiers() == ["smiles"]
    assert entries[2].identifiers() == ["ccd"]


def test_read_xlsx_and_template_roundtrip(tmp_path):
    p = write_template(tmp_path / "t.xlsx")
    entries, problems = read_library(p)
    assert not problems and len(entries) == 6
    assert {e.name for e in entries} == {"benzamidine", "aspirin", "caffeine", "imatinib", "ATP", "my_compound"}
    local = next(e for e in entries if e.name == "my_compound")
    assert local.sdf.endswith("my_compound.sdf") and str(tmp_path) in local.sdf   # relative to the sheet


def test_problems_are_listed_not_guessed(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("name,cid,inchikey\nA,12,\nA,13,\n,14,\nB,abc,\nC,,NOTAKEY\nD,,\n", encoding="utf-8")
    entries, problems = read_library(p)
    assert [e.name for e in entries] == ["A"]
    joined = "\n".join(problems)
    assert "重複" in joined and "沒有名稱" in joined and "不是整數 CID" in joined and "inchikey" in joined and "沒有任何識別資料" in joined


def test_missing_name_or_identifier_columns(tmp_path):
    p = tmp_path / "x.csv"; p.write_text("foo,bar\n1,2\n", encoding="utf-8")
    entries, problems = read_library(p)
    assert not entries and any("名稱欄" in q for q in problems) and any("識別欄" in q for q in problems)


def test_name_clash_after_safe_name(tmp_path):
    p = tmp_path / "x.csv"; p.write_text("name,smiles\nlig 1,C\nlig/1,CC\n", encoding="utf-8")
    entries, problems = read_library(p)
    assert len(entries) == 1 and "lig_1" in problems[0]


# ----------------------------------------------------------------------------- network layer
def test_retry_backoff_and_retry_after():
    calls, sleeps = [], []
    def fetch(url, headers):
        calls.append(url)
        if len(calls) == 1:
            raise FetchError("503", status=503)
        if len(calls) == 2:
            raise FetchError("429", status=429, retry_after=2.5)
        return b"ok"
    assert fetch_with_retry(fetch, "u", sleep=sleeps.append) == b"ok"
    assert sleeps == [1.0, 2.5] and len(calls) == 3


def test_4xx_fails_immediately():
    n = {"c": 0}
    def fetch(url, headers):
        n["c"] += 1; raise FetchError("404", status=404)
    with pytest.raises(FetchError):
        fetch_with_retry(fetch, "u", sleep=lambda s: None)
    assert n["c"] == 1


def test_gives_up_after_retries():
    def fetch(url, headers):
        raise FetchError("boom")
    with pytest.raises(FetchError, match="重試 3 次"):
        fetch_with_retry(fetch, "u", retries=3, sleep=lambda s: None)


def test_rate_limiter_spaces_requests(monkeypatch):
    t = {"now": 0.0}; slept = []
    monkeypatch.setattr("md20.docking.library.time.monotonic", lambda: t["now"])
    monkeypatch.setattr("md20.docking.library.time.sleep", lambda s: (slept.append(s), t.__setitem__("now", t["now"] + s)))
    rl = RateLimiter(4.0)
    rl.wait(); rl.wait(); rl.wait()
    assert slept and all(abs(s - 0.25) < 1e-9 for s in slept)


# ----------------------------------------------------------------------------- resolve
class FakeNet:
    """Serves PubChem / ChEMBL / RCSB URLs; records every request."""
    def __init__(self, *, no3d=(), fail=()):
        self.urls, self.no3d, self.fail = [], set(no3d), set(fail)

    def __call__(self, url, headers):
        self.urls.append(url)
        assert "User-Agent" in headers
        if any(f in url for f in self.fail):
            raise FetchError("HTTP 500 " + url, status=500)
        if url.startswith(PUBCHEM + "/compound/cid/"):
            cid = url.split("/cid/")[1].split("/")[0]
            if "record_type=3d" in url:
                if cid in self.no3d:
                    raise FetchError("404", status=404)
                return f"{cid}-3d{SDF}".encode()
            return f"{cid}-2d{SDF}".encode()
        if url.startswith(PUBCHEM + "/compound/inchikey/"):
            return json.dumps({"IdentifierList": {"CID": [777]}}).encode()
        if url.startswith(PUBCHEM + "/compound/name/"):
            return json.dumps({"IdentifierList": {"CID": [555]}}).encode()
        if url.startswith(CHEMBL):
            return json.dumps({"molecule_structures": {"canonical_smiles": "CCO"}}).encode()
        if url.startswith(RCSB_LIGAND):
            return f"ccd{SDF}".encode()
        raise AssertionError(url)


def _entries(tmp_path, text):
    p = tmp_path / "lib.csv"; p.write_text(text, encoding="utf-8")
    e, pr = read_library(p)
    assert not pr, pr
    return e


def test_resolve_sources_and_manifest(tmp_path):
    (tmp_path / "loc.sdf").write_text(SDF)
    ents = _entries(tmp_path, "name,smiles,cid,inchikey,ccd,sdf\n"
                              "a,,2244,,,\nb,,,RYYVLZVUVIJVGH-UHFFFAOYSA-N,,\nc,,,,ATP,\nd,,,,,loc.sdf\n")
    net = FakeNet(no3d={"777"})
    dec = DecisionLog(tmp_path / "dec.jsonl")
    man = resolve_library(ents, tmp_path / "lib", fetch=net, decisions=dec, workers=1, sleep=lambda s: None)
    st = {k: v["status"] for k, v in man["entries"].items()}
    assert st == {"a": "OK", "b": "OK", "c": "OK", "d": "OK"}
    assert man["entries"]["a"]["source"] == "pubchem-3d"
    assert man["entries"]["b"]["source"] == "pubchem-2d" and man["entries"]["b"]["pubchem_cid"] == "777"   # 3D missing → 2D fallback, recorded
    assert man["entries"]["c"]["source"] == "rcsb-ccd-ideal"
    assert man["entries"]["d"]["source"] == "local-sdf"
    assert all(man["entries"][k]["checked"] is False for k in st)      # no RDKit here: honest flag
    assert man["summary"] == {"OK": 4, "FAILED": 0, "SKIPPED": 0, "total": 4}
    assert man["order"] == ["a", "b", "c", "d"]
    assert (tmp_path / "lib" / "a.sdf").read_text().startswith("2244-3d")
    assert any(r["what"] == "resolve" for r in dec.read())


def test_failure_recorded_not_dropped_and_rerun_reuses_cache(tmp_path):
    ents = _entries(tmp_path, "name,cid\nok1,1\nbad,2\nok2,3\n")
    net = FakeNet(fail={"/cid/2/"})
    man = resolve_library(ents, tmp_path / "lib", fetch=net, workers=2, sleep=lambda s: None)
    assert man["entries"]["bad"]["status"] == "FAILED" and "HTTP 500" in man["entries"]["bad"]["error"]
    assert not (tmp_path / "lib" / "bad.sdf").exists()
    assert [u["name"] for u in usable_entries(man)] == ["ok1", "ok2"]
    assert [p["name"] for p in problem_entries(man)] == ["bad"]
    n_first = len(net.urls)
    net2 = FakeNet()
    man2 = resolve_library(ents, tmp_path / "lib", fetch=net2, workers=1, sleep=lambda s: None)
    assert man2["entries"]["bad"]["status"] == "OK"
    assert all("/cid/2/" in u for u in net2.urls)          # only the failed one is fetched again
    assert n_first >= 4


def test_name_lookup_off_by_default(tmp_path):
    p = tmp_path / "lib.csv"; p.write_text("name,smiles\ncaffeine,\n", encoding="utf-8")
    ents, problems = read_library(p)
    assert not ents and "沒有任何識別資料" in problems[0]


def test_name_lookup_when_allowed_is_logged_as_human(tmp_path):
    from md20.docking.library import LibraryEntry
    dec = DecisionLog(tmp_path / "dec.jsonl")
    net = FakeNet()
    man = resolve_library([LibraryEntry(name="caffeine", label="caffeine", row=1)], tmp_path / "lib", fetch=net,
                          allow_name_lookup=True, decisions=dec, workers=1, sleep=lambda s: None)
    assert man["entries"]["caffeine"]["status"] == "OK" and man["entries"]["caffeine"]["pubchem_cid"] == "555"
    assert "核對" in man["entries"]["caffeine"]["note"]
    assert any(r["kind"] == "human" and "name lookup" in r["choice"] for r in dec.read())


def test_chembl_without_rdkit_is_failed_honestly(tmp_path):
    ents = _entries(tmp_path, "name,chembl_id\nx,CHEMBL941\n")
    man = resolve_library(ents, tmp_path / "lib", fetch=FakeNet(), workers=1, sleep=lambda s: None)
    r = man["entries"]["x"]
    assert r["status"] == "FAILED" and "RDKit" in r["error"]


def test_progress_callback_counts_every_entry(tmp_path):
    ents = _entries(tmp_path, "name,cid\na,1\nb,2\nc,3\n")
    seen = []
    resolve_library(ents, tmp_path / "lib", fetch=FakeNet(), workers=3, progress_cb=seen.append, sleep=lambda s: None)
    assert sorted(e["i"] for e in seen) == [1, 2, 3] and all(e["n"] == 3 for e in seen)


def test_filters_from_cfg_ignores_unknown_keys():
    f = LibraryFilters.from_cfg({"max_mw": 500, "bogus": 1})
    assert f.max_mw == 500 and f.min_heavy_atoms == 5
