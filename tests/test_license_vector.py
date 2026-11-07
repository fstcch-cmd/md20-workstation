"""D-127: the licence format is shared with the owner's private signing repository through a test vector
(`tests/data/license_vector_v1.json`, a copy of that repository's `test_vectors/v1.json`).  The vector holds a TEST public key and
signatures made with its throw-away private key; the private key was discarded.  This key is only ever put into
`TRUSTED_KEYS` by these tests (monkeypatch) and must never be added to the real list."""
import base64
import copy
import datetime as dt
import json
from pathlib import Path

import pytest

from md20.util import license as L

VEC_PATH = Path(__file__).resolve().parent / "data" / "license_vector_v1.json"


@pytest.fixture(scope="module")
def vec():
    return json.loads(VEC_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def trust_vector_key(vec, monkeypatch):
    monkeypatch.setattr(L, "TRUSTED_KEYS", [vec["public_key_pem"].encode("ascii")])
    L._reset_cache()


def _doc(e):
    return {"payload": e["payload"], "sig": e["sig"]}


def test_vector_has_no_private_key_and_is_not_trusted_by_the_product(vec):
    text = VEC_PATH.read_text(encoding="utf-8")
    assert ("PRIVATE" + " KEY") not in text
    shipped = Path(L.__file__).with_name("owner_pub.pem").read_bytes()
    assert vec["public_key_pem"].encode("ascii") != shipped
    assert vec["public_key_pem"].encode("ascii").strip() not in shipped            # the real TRUSTED_KEYS never contained it
    assert "WARNING" in vec["warning"].upper() or "TEST KEY ONLY" in vec["warning"]


def test_message_bytes_match_the_spec(vec):
    assert len(vec["vectors"]) >= 3
    for e in vec["vectors"]:
        message = L.DOMAIN + L.canonical(e["payload"])
        assert message.decode("utf-8") == e["message_utf8"], e["name"]


def test_every_vector_signature_is_accepted(vec, trust_vector_key):
    for e in vec["vectors"]:
        assert L.signature_ok(_doc(e)), e["name"]


def test_tampered_vectors_are_rejected(vec, trust_vector_key):
    for e in vec["vectors"]:
        for field, value in (("licensee", "Mallory"), ("expires", "2000-01-01"), ("scope", "x"), ("machines", ["0000-0000-0000-0000"]), ("id", "f" * 16)):
            bad = copy.deepcopy(_doc(e)); bad["payload"][field] = value
            assert not L.signature_ok(bad), (e["name"], field)
        sig = bytearray(base64.b64decode(e["sig"])); sig[7] ^= 1
        assert not L.signature_ok({"payload": e["payload"], "sig": base64.b64encode(bytes(sig)).decode()})
        assert not L.signature_ok({"payload": e["payload"], "sig": ""})


def test_the_vector_key_is_rejected_when_not_trusted(vec):
    """Without the monkeypatch (the autouse fixture trusts only a per-test key) the vector licence is not valid."""
    for e in vec["vectors"]:
        assert not L.signature_ok(_doc(e))
        assert L.evaluate(_doc(e)).state == L.BAD_SIGNATURE


def test_evaluation_of_the_vectors(vec, trust_vector_key, monkeypatch):
    by = {e["name"]: e for e in vec["vectors"]}
    basic = L.evaluate(_doc(by["basic-any-computer"]))
    assert basic.ok and basic.licensee == "Test Student" and basic.expires == "2099-12-31"
    uni = by["unicode-bound-no-expiry"]
    assert L.evaluate(_doc(uni)).state == L.WRONG_MACHINE
    monkeypatch.setattr(L, "machine_code", lambda: "AAAA-BBBB-CCCC-DDDD")
    L._reset_cache()
    st = L.evaluate(_doc(uni))
    assert st.ok and st.licensee == uni["payload"]["licensee"] and st.expires is None
    assert L.evaluate(_doc(by["scope-all"])).ok
    monkeypatch.setattr(L, "_today", lambda: dt.date(2100, 1, 1))
    assert L.evaluate(_doc(by["basic-any-computer"])).state == L.EXPIRED


def test_installing_a_vector_licence(vec, trust_vector_key, license_env, tmp_path):
    license_env.clear()
    f = tmp_path / "v.md20license"
    f.write_text(json.dumps(_doc(vec["vectors"][0]), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    st = L.install(f)
    assert st.ok and (license_env.dir / (vec["vectors"][0]["payload"]["id"] + L.EXT)).is_file()
