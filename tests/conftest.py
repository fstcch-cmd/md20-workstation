import urllib.request

import pytest


# ---- D-125 / D-127: real calculations need a signed licence (the signer here is only a test helper: tests/_license_testkit.py).
# Every test gets a throw-away key pair (the owner's real private
# key does not exist here) and a licence signed with it in a temporary licence folder.  This is done in-process by
# patching module attributes; there is deliberately no environment variable or option that does it (see util/license.py).
@pytest.fixture(scope="session")
def license_keys():
    from _license_testkit import keygen_pair
    return keygen_pair(2048)


@pytest.fixture(scope="session")
def _test_license_doc(license_keys):
    from _license_testkit import make_payload, sign_payload
    key, pub = license_keys
    return sign_payload(make_payload("pytest", scope="use", note="test licence"), key)


class LicenseEnv:
    """What a test can do with the licence folder: `clear()` removes every licence; `put(doc)` adds one."""

    def __init__(self, directory, key, pub):
        self.dir, self.key, self.pub = directory, key, pub

    def clear(self):
        from md20.util import license as L
        for f in self.dir.glob("*" + L.EXT):
            f.unlink()
        L._reset_cache()

    def put(self, doc, name=None):
        import json
        from md20.util import license as L
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / (name or doc["payload"]["id"] + L.EXT)).write_text(json.dumps(doc), encoding="utf-8")
        L._reset_cache()

    def issue(self, name="pytest", **kw):
        from _license_testkit import make_payload, sign_payload
        return sign_payload(make_payload(name, **kw), self.key)


@pytest.fixture(autouse=True)
def license_env(monkeypatch, tmp_path_factory, license_keys, _test_license_doc):
    from md20.util import license as L
    key, pub = license_keys
    d = tmp_path_factory.mktemp("lic")
    monkeypatch.setattr(L, "TRUSTED_KEYS", [pub])
    monkeypatch.setattr(L, "license_dir", lambda: d)
    monkeypatch.setattr(L, "BUNDLED_DIR", d / "_none")
    env = LicenseEnv(d, key, pub)
    env.put(_test_license_doc)
    yield env
    L._reset_cache()


@pytest.fixture(scope="session")
def pdb_3ptb(tmp_path_factory):
    """Bovine trypsin + benzamidine (3PTB).  Downloaded once per session; skips offline."""
    d = tmp_path_factory.mktemp("rcsb")
    p = d / "3PTB.pdb"
    try:
        urllib.request.urlretrieve("https://files.rcsb.org/download/3PTB.pdb", p)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"RCSB unreachable: {exc}")
    return p


@pytest.fixture(scope="session")
def pdb_ca2(tmp_path_factory):
    """Human carbonic anhydrase II (3KS3): Zn bound by His94/His96/His119 + water.  Skips offline."""
    d = tmp_path_factory.mktemp("rcsb_ca2")
    p = d / "3KS3.pdb"
    try:
        urllib.request.urlretrieve("https://files.rcsb.org/download/3KS3.pdb", p)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"RCSB unreachable: {exc}")
    return p
