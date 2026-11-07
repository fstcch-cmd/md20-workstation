"""D-128: licence format v2 and the revocation list are shared with the owner's private signing repository through
`tests/data/license_vector_v2.json` (a byte-for-byte copy of that repository's `test_vectors/v2.json`).  The vector holds a TEST
public key; its private key was discarded.  The key is only put into TRUSTED_KEYS by these tests (monkeypatch)."""
import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest

from md20.util import license as L

VEC_PATH = Path(__file__).resolve().parent / "data" / "license_vector_v2.json"
# the signing repository pins the same value: both copies are the same bytes
VEC_SHA256 = "e05050cd2bd2849e4dabbba096451a8d1438beb8335b1d18533df8c11817efff"


@pytest.fixture(scope="module")
def vec():
    return json.loads(VEC_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def trust_vector_key(vec, monkeypatch):
    monkeypatch.setattr(L, "TRUSTED_KEYS", [vec["public_key_pem"].encode("ascii")])
    L._reset_cache()


def _doc(e):
    return {"payload": e["payload"], "sig": e["sig"]}


def test_the_vector_file_is_the_one_the_signing_repository_published():
    assert hashlib.sha256(VEC_PATH.read_bytes()).hexdigest() == VEC_SHA256


def test_vector_has_no_private_key_and_is_not_trusted_by_the_product(vec):
    text = VEC_PATH.read_text(encoding="utf-8")
    assert ("PRIVATE" + " KEY") not in text
    shipped = Path(L.__file__).with_name("owner_pub.pem").read_bytes()
    pub = vec["public_key_pem"].encode("ascii")
    assert pub != shipped and pub.strip() not in shipped
    assert L.key_fingerprint(pub) == vec["public_key_fingerprint"] != L.key_fingerprint(shipped)
    assert pub not in L.TRUSTED_KEYS
    v1 = json.loads((VEC_PATH.parent / "license_vector_v1.json").read_text(encoding="utf-8"))
    assert vec["public_key_pem"] != v1["public_key_pem"]


def test_message_bytes_match_the_spec(vec):
    assert vec["domains"] == {"licence_v1": "md20-license-v1\n", "licence_v2": "md20-license-v2\n", "revocations": "md20-revocations-v1\n"}
    assert (L.DOMAIN, L.DOMAIN_V2, L.REV_DOMAIN) == tuple(vec["domains"][k].encode() for k in ("licence_v1", "licence_v2", "revocations"))
    for e in vec["vectors"]:
        assert (L.DOMAIN_V2 + L.canonical(e["payload"])).decode("utf-8") == e["message_utf8"], e["name"]
        assert hashlib.sha256(e["message_utf8"].encode("utf-8")).hexdigest() == e["message_sha256"]
    for e in vec["revocations"]:
        assert (L.REV_DOMAIN + L.canonical(e["payload"])).decode("utf-8") == e["message_utf8"], e["name"]


def test_every_v2_licence_is_accepted_and_read_as_expected(vec, trust_vector_key, monkeypatch):
    monkeypatch.setattr(L, "machine_code", lambda: "1111-2222-3333-4444")
    L._reset_cache()
    tiers = set()
    for e in vec["vectors"]:
        assert L.signature_ok(_doc(e)), e["name"]
        st = L.evaluate(_doc(e), revoked=None)
        assert st.schema == L.SCHEMA_V2
        if e["name"] == "v2-unicode":                            # bound to another machine
            assert st.state == L.WRONG_MACHINE
        else:
            assert st.ok, (e["name"], st.detail)
        ex = e["expect"]
        assert (st.tier, "all" if st.features is None else st.features, st.org, st.seats, st.max_version) == \
            (ex["tier"], ex["features"], ex["org"], ex["seats"], ex["max_version"]), e["name"]
        tiers.add(st.tier)
    assert set(L.TIERS) <= tiers


def test_features_and_limits_of_the_vectors(vec, trust_vector_key, monkeypatch):
    by = {e["name"]: e for e in vec["vectors"]}
    research = L.evaluate(_doc(by["v2-research-features-seats"]), revoked=None)
    assert research.allows("binding") and research.allows("hts") and not research.allows("membrane") and not research.allows("cg")
    assert L.evaluate(_doc(by["v2-minimal"]), revoked=None).allows("cg")
    commercial = by["v2-commercial-maxversion"]
    monkeypatch.setattr(L, "_app_version", lambda: "0.1.0a19")
    monkeypatch.setattr(L, "machine_code", lambda: "AAAA-BBBB-CCCC-DDDD")
    assert L.evaluate(_doc(commercial), revoked=None).ok
    monkeypatch.setattr(L, "_app_version", lambda: "0.1.1")
    assert L.evaluate(_doc(commercial), revoked=None).state == L.VERSION_LIMIT
    site = L.evaluate(_doc(by["v2-site"]), revoked=None)
    assert site.ok and site.machines == [] and site.org == "Test 大學"          # bound to the organisation, any computer


def test_tampered_v2_vectors_are_rejected(vec, trust_vector_key):
    for e in vec["vectors"]:
        for field, value in (("licensee", "Mallory"), ("tier", "commercial"), ("features", ["all"]), ("seats", 99),
                             ("max_version", "99.0"), ("org", "X"), ("expires", "2000-01-01"), ("scope", "all")):
            bad = copy.deepcopy(_doc(e)); bad["payload"][field] = value
            if bad["payload"] == e["payload"]:
                continue
            assert not L.signature_ok(bad), (e["name"], field)
        dropped = copy.deepcopy(_doc(e))
        for f in ("tier", "features", "seats", "max_version", "org"):
            if f in dropped["payload"]:
                del dropped["payload"][f]
                assert not L.signature_ok(dropped), (e["name"], f)            # removing a restriction breaks the signature
                break
        sig = bytearray(base64.b64decode(e["sig"])); sig[7] ^= 1
        assert not L.signature_ok({"payload": e["payload"], "sig": base64.b64encode(bytes(sig)).decode()})


def test_the_vector_key_is_rejected_when_not_trusted(vec):
    for e in vec["vectors"]:
        assert L.evaluate(_doc(e)).state == L.BAD_SIGNATURE
    for e in vec["revocations"]:
        with pytest.raises(ValueError):
            L.parse_revocations(_doc(e))


def test_revocation_vectors(vec, trust_vector_key):
    r1, r2 = (L.parse_revocations(_doc(e)) for e in vec["revocations"])
    assert r2.issued_at > r1.issued_at and r1.ids <= r2.ids
    by = {e["name"]: e["payload"]["id"] for e in vec["vectors"]}
    ev = next(e for e in vec["vectors"] if e["name"] == "v2-evaluation")
    site = next(e for e in vec["vectors"] if e["name"] == "v2-site")
    assert by["v2-evaluation"] in r1.ids and by["v2-site"] not in r1.ids and by["v2-site"] in r2.ids
    assert L.evaluate(_doc(ev), revoked=r1).state == L.REVOKED
    assert L.evaluate(_doc(site), revoked=r1).ok and L.evaluate(_doc(site), revoked=r2).state == L.REVOKED


def test_wrong_prefix_signatures_are_rejected(vec, trust_vector_key):
    assert len(vec["negative_vectors"]) >= 4
    for e in vec["negative_vectors"]:
        assert e["expect_signature"] == "invalid"
        if e["kind"] == "licence":
            assert not L.signature_ok(_doc(e)), e["name"]
            assert L.evaluate(_doc(e), revoked=None).state == L.BAD_SIGNATURE
        else:
            with pytest.raises(ValueError):
                L.parse_revocations(_doc(e))
