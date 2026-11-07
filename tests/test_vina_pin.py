"""D-114 (REVIEW #19): Vina executable is one pinned release, checked by sha256; 'latest' is opt-in only."""
import hashlib

import pytest

from md20.docking import vina_cli as V


@pytest.fixture
def fake_net(monkeypatch, tmp_path):
    calls = {"api": 0, "dl": []}

    def urlopen(*a, **k):
        calls["api"] += 1
        raise AssertionError("releases API must not be called by default")

    def urlretrieve(url, dest):
        calls["dl"].append(url)
        open(dest, "wb").write(calls.get("payload", b"official bytes"))

    monkeypatch.setattr(V.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(V.urllib.request, "urlretrieve", urlretrieve)
    monkeypatch.setattr(V, "find_vina_exe", lambda: None)
    monkeypatch.delenv("MD20_VINA_LATEST", raising=False)
    name = V._pinned_name()
    monkeypatch.setitem(V.KNOWN_SHA256, name, hashlib.sha256(b"official bytes").hexdigest())
    return calls


def test_default_downloads_only_the_pinned_release_and_verifies_it(fake_net, tmp_path):
    exe = V.ensure_vina_exe(tmp_path)
    assert fake_net["api"] == 0 and len(fake_net["dl"]) == 1 and f"/{V.PINNED_VERSION}/" in fake_net["dl"][0]
    assert V.sha256_file(exe) == hashlib.sha256(b"official bytes").hexdigest()


def test_hash_mismatch_is_rejected_and_nothing_is_left_behind(fake_net, tmp_path):
    fake_net["payload"] = b"tampered or truncated"
    with pytest.raises(RuntimeError, match="sha256"):
        V.ensure_vina_exe(tmp_path)
    assert not any(tmp_path.iterdir())                    # no vina, no .part


def test_latest_is_opt_in(fake_net, tmp_path, monkeypatch):
    monkeypatch.setenv("MD20_VINA_LATEST", "1")
    errs = []
    urls = V._candidate_urls(errs)                         # API raises → recorded, pinned still offered
    assert fake_net["api"] == 1 and errs and urls[-1][0].endswith(V._pinned_name()) and urls[-1][1]


def test_every_pinned_asset_has_a_hash_and_identity_is_recognised(tmp_path):
    assert set(V.PINNED_ASSETS.values()) <= set(V.KNOWN_SHA256)
    assert all(len(h) == 64 for h in V.KNOWN_SHA256.values()) and len(set(V.KNOWN_SHA256.values())) == len(V.KNOWN_SHA256)
    f = tmp_path / "vina"
    f.write_bytes(b"x")
    idn = V.vina_exe_identity(f)
    assert idn["asset"] is None and idn["version"] is None and idn["sha256"] == hashlib.sha256(b"x").hexdigest()


def test_identity_of_a_known_asset(tmp_path, monkeypatch):
    f = tmp_path / "vina.exe"
    f.write_bytes(b"old pin")
    monkeypatch.setitem(V.KNOWN_SHA256, "vina_1.2.5_win.exe", hashlib.sha256(b"old pin").hexdigest())
    idn = V.vina_exe_identity(f)
    assert idn["asset"] == "vina_1.2.5_win.exe" and idn["version"] == "v1.2.5" and idn["pinned"] is False
