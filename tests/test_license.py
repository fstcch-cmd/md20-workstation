"""D-125 / D-127: signed licence.  Real calculations need one; viewing, diagnostics and the demo do not.  The product only
verifies; tests sign with the helper in tests/_license_testkit.py (issuing lives in the owner's private repository).

tests/conftest.py gives every test a throw-away key pair, patches `TRUSTED_KEYS` and installs a test licence in a temporary
folder.  Tests that need "no licence" call `license_env.clear()`."""
import base64
import copy
import csv
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from md20 import cli
from md20.util import license as L
from md20.util import stamp
import _license_testkit as K


@pytest.fixture
def machine(monkeypatch):
    monkeypatch.setattr(L, "machine_code", lambda: "AAAA-BBBB-CCCC-DDDD")
    L._reset_cache()
    return "AAAA-BBBB-CCCC-DDDD"


def _write(tmp_path, doc, name="x.md20license"):
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


# ------------------------------------------------------------------------------------------------ sign and verify
def test_issue_then_verify(license_env):
    doc = license_env.issue("王小明", days=30, note="N")
    st = L.evaluate(doc)
    assert st.ok and st.licensee == "王小明" and st.scope == "use"
    assert st.expires == (dt.date.today() + dt.timedelta(days=30)).isoformat()
    p = doc["payload"]
    assert set(p) == {"schema", "id", "licensee", "issued_at", "expires", "machines", "scope", "note", "issuer"}
    assert len(p["id"]) == 16 and p["schema"] == L.SCHEMA and p["issuer"] == K.ISSUER


def test_signature_is_rsa_pss_sha256(license_env):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    doc = license_env.issue("A")
    pub = serialization.load_pem_public_key(license_env.pub)
    sig = base64.b64decode(doc["sig"])
    pub.verify(sig, L.DOMAIN + L.canonical(doc["payload"]),
               padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
    with pytest.raises(Exception):               # the bare payload without the domain prefix is not what was signed
        pub.verify(sig, L.canonical(doc["payload"]),
                   padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())


def test_canonical_json_is_stable():
    a = {"b": 1, "a": ["x", "名"], "c": None}
    b = {"c": None, "a": ["x", "名"], "b": 1}
    assert L.canonical(a) == L.canonical(b) == '{"a":["x","名"],"b":1,"c":null}'.encode("utf-8")


@pytest.mark.parametrize("field,value", [("licensee", "Mallory"), ("expires", "2099-01-01"), ("scope", "all"), ("machines", ["1111-2222-3333-4444"]),
                                         ("id", "0" * 16)])
def test_tampered_payload_is_rejected(license_env, field, value):
    doc = license_env.issue("Alice", days=5)
    bad = copy.deepcopy(doc)
    bad["payload"][field] = value
    assert L.evaluate(bad).state == L.BAD_SIGNATURE


def test_tampered_or_missing_signature_is_rejected(license_env):
    doc = license_env.issue("Alice")
    sig = bytearray(base64.b64decode(doc["sig"])); sig[3] ^= 1
    assert L.evaluate({"payload": doc["payload"], "sig": base64.b64encode(bytes(sig)).decode()}).state == L.BAD_SIGNATURE
    assert L.evaluate({"payload": doc["payload"], "sig": ""}).state == L.BAD_SIGNATURE
    assert L.evaluate({"payload": doc["payload"], "sig": "not base64!!"}).state == L.BAD_SIGNATURE
    assert L.evaluate({"payload": doc["payload"]}).state == L.BAD_SIGNATURE
    assert L.evaluate("nonsense").state == L.BAD_SIGNATURE


def test_signed_by_another_key_is_rejected(license_env, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import rsa
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(L, "TRUSTED_KEYS", [license_env.pub, ])
    forged = K.sign_payload(K.make_payload("Mallory"), other)
    assert L.evaluate(forged).state == L.BAD_SIGNATURE


def test_a_second_trusted_key_also_works(license_env, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    new = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    new_pub = new.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(L, "TRUSTED_KEYS", [license_env.pub, new_pub])
    assert L.evaluate(K.sign_payload(K.make_payload("New key"), new)).ok
    assert L.evaluate(license_env.issue("Old key")).ok


def test_signature_of_an_oaep_stamp_or_other_message_is_not_a_licence(license_env):
    """Domain separation: a PSS signature over the bare payload (no DOMAIN prefix) never verifies as a licence."""
    payload = K.make_payload("Bob")
    pad, algo = K.pss_for_signing()
    sig = license_env.key.sign(L.canonical(payload), pad, algo)
    assert L.evaluate({"payload": payload, "sig": base64.b64encode(sig).decode()}).state == L.BAD_SIGNATURE


# ------------------------------------------------------------------------------------------------ expiry, machine, scope
def test_expiry(license_env, monkeypatch):
    doc = license_env.issue("A", expires="2030-06-30")
    for today, ok in ((dt.date(2030, 6, 29), True), (dt.date(2030, 6, 30), True), (dt.date(2030, 7, 1), False)):
        monkeypatch.setattr(L, "_today", lambda t=today: t)
        st = L.evaluate(doc)
        assert (st.state == (L.VALID if ok else L.EXPIRED)), today
    assert "2030-06-30" in st.message("en")
    # no expiry = valid whenever
    monkeypatch.setattr(L, "_today", lambda: dt.date(2090, 1, 1))
    assert L.evaluate(license_env.issue("B")).ok


def test_machine_binding(license_env, machine):
    ok = license_env.issue("A", machines=[machine.lower().replace("-", " ")])
    assert L.evaluate(ok).ok and ok["payload"]["machines"] == [machine]
    other = license_env.issue("A", machines=["1111-2222-3333-4444"])
    assert L.evaluate(other).state == L.WRONG_MACHINE
    both = license_env.issue("A", machines=["1111-2222-3333-4444", machine])
    assert L.evaluate(both).ok
    with pytest.raises(ValueError):
        L.normalize_machine("1234")


def test_scope_all_ignores_machines_and_needs_a_signature(license_env, machine, tmp_path):
    doc = license_env.issue("Everyone", scope="all", expires="2999-12-31")
    assert L.evaluate(doc).ok
    both = K.make_payload("X", machines=["1111-2222-3333-4444"]); both["scope"] = "all"          # the signer refuses this; the verifier still ignores machines
    assert L.evaluate(K.sign_payload(both, license_env.key)).ok
    forged = copy.deepcopy(license_env.issue("X", machines=["1111-2222-3333-4444"]))
    forged["payload"]["scope"] = "all"
    assert L.evaluate(forged).state == L.BAD_SIGNATURE


def test_bundled_all_scope_licence_opens_every_computer(license_env, machine, tmp_path, monkeypatch):
    license_env.clear()
    b = tmp_path / "bundled"; b.mkdir()
    (b / ("open" + L.EXT)).write_text(json.dumps(license_env.issue("Open", scope="all")), encoding="utf-8")
    assert not L.status().ok
    monkeypatch.setattr(L, "BUNDLED_DIR", b)
    L._reset_cache()
    assert L.status().ok and L.status().scope == "all"


def test_status_prefers_a_valid_file_and_reports_the_most_informative_failure(license_env, machine, monkeypatch):
    license_env.clear()
    assert L.status().state == L.NONE and L.status().machine_code == machine
    junk = license_env.issue("J"); junk["payload"]["licensee"] = "tampered"
    license_env.put(junk, "a.md20license")
    assert L.status().state == L.BAD_SIGNATURE
    license_env.put(license_env.issue("W", machines=["1111-2222-3333-4444"]), "b.md20license")
    assert L.status().state == L.WRONG_MACHINE
    license_env.put(license_env.issue("E", expires="2000-01-01"), "c.md20license")
    assert L.status().state == L.EXPIRED
    license_env.put(license_env.issue("Good"), "d.md20license")
    assert L.status().ok and L.status().licensee == "Good"
    (license_env.dir / "e.md20license").write_text("{ not json", encoding="utf-8")      # unreadable files never crash it
    assert L.status().ok


def test_messages_have_four_languages_machine_code_and_instructions(license_env, machine):
    license_env.clear()
    st = L.status()
    for lang in L.LANG_ORDER:
        m = st.message(lang, with_howto=True)
        assert machine in m and "md20 license install" in m
    texts = {st.message(l) for l in L.LANG_ORDER}
    assert len(texts) == 4
    for state, tup in L.TEXT.items():
        assert len(tup) == 4 and all(tup)


# ------------------------------------------------------------------------------------------------ install
def test_install_copies_only_valid_files(license_env, machine, tmp_path):
    license_env.clear()
    good = license_env.issue("Alice", days=10)
    st = L.install(_write(tmp_path, good))
    assert st.ok and (license_env.dir / (good["payload"]["id"] + L.EXT)).is_file()
    assert L.status().ok and L.status().licensee == "Alice"
    license_env.clear()
    for doc in (license_env.issue("W", machines=["1111-2222-3333-4444"]), license_env.issue("E", expires="2000-01-01"),
                {"payload": good["payload"], "sig": "AAAA"}):
        with pytest.raises(L.LicenseError) as ei:
            L.install(_write(tmp_path, doc))
        assert len(ei.value.texts) == 4
        assert not list(license_env.dir.glob("*" + L.EXT))
    junk = tmp_path / "j.md20license"; junk.write_text("hello", encoding="utf-8")
    with pytest.raises(L.LicenseError):
        L.install(junk)
    big = tmp_path / "big.md20license"; big.write_text("x" * 100000, encoding="utf-8")
    with pytest.raises(L.LicenseError):
        L.install(big)
    with pytest.raises(L.LicenseError):
        L.install(tmp_path / "missing.md20license")


# ------------------------------------------------------------------------------------------------ gates
def test_no_licence_blocks_real_calculations_but_not_the_demo_or_looking(license_env, tmp_path, capsys):
    from md20.project import Project
    license_env.clear()
    root = tmp_path / "projects"
    proj = Project.create(root, "p")
    base = ["--dir", str(root)]
    # blocked
    assert cli.main(base + ["build", "--project", "p", "--case", "c", "--receptor", "r.pdb", "--ligand", "l.sdf"]) == cli.EXIT_LICENSE
    assert cli.main(base + ["run", "--project", "p", "--case", "c"]) == cli.EXIT_LICENSE
    assert cli.main(base + ["queue", "run", "--project", "p"]) == cli.EXIT_LICENSE
    cfg = tmp_path / "cfg.json"; cfg.write_text("{}", encoding="utf-8")
    assert cli.main(base + ["pipeline", "run", str(cfg)]) == cli.EXIT_LICENSE
    assert cli.main(base + ["fold", "GIGAVLKVLTTGLPALISWIKRKRQQ", "--engine", "upload", "--upload", str(cfg)]) == cli.EXIT_LICENSE
    err = capsys.readouterr().err
    assert err.count("md20 license install") >= 5 * 4 and "Machine code" in err and "機器碼" in err
    # not blocked
    assert cli.main(base + ["demo", "--dir", str(tmp_path / "demo")]) == 0
    assert cli.main(base + ["project", "list"]) == 0
    assert cli.main(base + ["status", "--project", "p"]) == 0
    assert cli.main(base + ["queue", "list", "--project", "p"]) == 0
    assert cli.main(base + ["pipeline", "example"]) == 0
    assert cli.main(base + ["screen", "template", "--out", str(tmp_path / "lib.xlsx")]) == 0
    assert cli.main(base + ["validate"]) != cli.EXIT_LICENSE               # lists the cases
    assert cli.main(base + ["resume", "--list"]) == 0
    assert cli.main(base + ["license", "status"]) == 1                      # says "no licence" without raising
    assert cli.main(base + ["license", "machine"]) == 0
    assert cli.main(base + ["stamp", "verify", str(tmp_path / "lib.xlsx")]) == 0
    assert cli.main(base + ["doctor", "--no-benchmark"]) != cli.EXIT_LICENSE


def test_the_fake_backend_commands_need_no_licence(license_env, tmp_path):
    from md20.project import Project
    license_env.clear()
    proj = Project.create(tmp_path / "pr", "p")
    proj.new_case("c")
    # reaches the real code (and fails there for its own reasons), not the licence exit code
    try:
        rc = cli.main(["--dir", str(tmp_path / "pr"), "run", "--project", "p", "--case", "c", "--fake"])
    except Exception:  # noqa: BLE001
        rc = 0
    assert rc != cli.EXIT_LICENSE
    from md20.engine.factory import make_backend_factory
    assert callable(make_backend_factory(None, None, fake=True))
    with pytest.raises(L.LicenseRequired):
        make_backend_factory(None, None, fake=False)


def test_resume_is_gated_when_something_would_run(license_env, tmp_path):
    from md20.project import Project
    from md20.workflow import Workflow, example_config
    license_env.clear()
    proj = Project.create(tmp_path / "pr", "p")
    Workflow(proj, example_config())
    assert cli.main(["--dir", str(tmp_path / "pr"), "resume"]) == cli.EXIT_LICENSE


def test_workflow_run_is_gated_even_with_the_fake_backend(license_env, tmp_path, monkeypatch):
    from md20.project import Project
    from md20.workflow import Workflow, example_config
    wf = Workflow(Project.create(tmp_path / "pr", "p"), example_config())
    license_env.clear()
    monkeypatch.setenv("MD20_GUI_FAKE_RUN", "1")
    with pytest.raises(L.LicenseRequired):
        wf.run(lambda case, proto: None, platform=None)


def test_gui_process_entry_is_gated_but_the_stand_in_is_not(license_env, tmp_path, monkeypatch):
    from md20.project import Project
    from md20.workflow import Workflow, example_config
    from md20.gui import worker as W
    from md20.gui import logic as GL
    wf = Workflow(Project.create(tmp_path / "pr", "p"), example_config())
    license_env.clear()
    started = []
    runner = GL.Runner(launcher=lambda w: started.append(w) or type("P", (), {"poll": lambda self: None})())
    monkeypatch.delenv("MD20_GUI_FAKE_RUN", raising=False)
    with pytest.raises(L.LicenseRequired):
        runner.start_process(wf)
    assert started == []                                             # no process was launched
    with pytest.raises(L.LicenseRequired):
        W._real_run(wf, tmp_path / "pr", lambda ev: None)
    info = W.run_worker(wf.project.dir, wf.name)                      # the real worker reports it in four languages
    assert info["status"] == "ERROR" and len(info["message"]) == 4 and "md20 license install" in info["message"][1]
    # the stand-in does no chemistry and is not blocked
    monkeypatch.setenv("MD20_GUI_FAKE_RUN", "1")
    monkeypatch.setattr(GL, "_fake_run", lambda w, s, cb: {"status": "COMPLETE"})
    assert W._real_run(wf, tmp_path / "pr", lambda ev: None) == {"status": "COMPLETE"}
    runner.start_process(wf)
    assert len(started) == 1


def test_gui_blocked_start_returns_a_placeholder(license_env, tmp_path):
    pytest.importorskip("nicegui")
    from md20.gui import app as A
    from md20.project import Project
    from md20.workflow import Workflow, example_config
    wf = Workflow(Project.create(tmp_path / "pr", "p"), example_config())
    assert A._Blocked(wf).blocked and not A._Blocked(wf).alive()


# ------------------------------------------------------------------------------------------------ no way around it from outside
OUTSIDE_SWITCHES = ["MD20_LICENSE", "MD20_LICENSE_FILE", "MD20_LICENSE_KEY", "MD20_LICENSE_PUBKEY", "MD20_TRUSTED_KEYS", "MD20_PUBKEY",
                    "MD20_NO_LICENSE", "MD20_SKIP_LICENSE", "MD20_DISABLE_LICENSE", "MD20_LICENSE_OFF", "MD20_DEV", "MD20_DEBUG",
                    "MD20_CI", "MD20_CI_LICENSE", "MD20_TEST", "MD20_STACK", "MD20_HEAVY", "MD20_CG", "MD20_PAPERS", "CI",
                    "GITHUB_ACTIONS", "PYTEST_CURRENT_TEST", "MD20_OWNER", "MD20_UNLOCK", "MD20_FREE"]


def test_no_environment_variable_makes_an_unsigned_licence_pass(license_env, tmp_path, monkeypatch):
    license_env.clear()
    for k in OUTSIDE_SWITCHES:
        monkeypatch.setenv(k, "1")
    unsigned = K.make_payload("Mallory", scope="all")
    license_env.put({"payload": unsigned, "sig": "AAAA"})
    from cryptography.hazmat.primitives.asymmetric import rsa
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pad, algo = K.pss_for_signing()
    license_env.put({"payload": unsigned, "sig": base64.b64encode(other.sign(L.DOMAIN + L.canonical(unsigned), pad, algo)).decode()}, "other.md20license")
    assert not L.status().ok
    with pytest.raises(L.LicenseRequired):
        L.require()


def test_the_licence_module_reads_nothing_from_the_environment():
    src = Path(L.__file__).read_text(encoding="utf-8")
    import re
    assert not re.search(r"\benviron\b|getenv|\bargv\b", src)


def test_unlicensed_subprocess_is_refused_whatever_the_environment(tmp_path):
    """A real child process with the shipped owner public key, an empty licence folder and every switch set."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    empty = tmp_path / "home"; empty.mkdir()
    env.update(HOME=str(empty), XDG_DATA_HOME=str(empty / "x"), LOCALAPPDATA=str(empty / "l"), APPDATA=str(empty / "a"),
               USERPROFILE=str(empty), PYTHONUTF8="1")
    env.update({k: "1" for k in OUTSIDE_SWITCHES if k != "PYTEST_CURRENT_TEST"})
    r = subprocess.run([sys.executable, "-m", "md20", "--dir", str(tmp_path / "pr"), "run", "--project", "p", "--case", "c"],
                       env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == cli.EXIT_LICENSE, r.stdout + r.stderr
    assert "Machine code" in r.stderr
    r = subprocess.run([sys.executable, "-m", "md20", "license", "machine"], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and len(r.stdout.strip()) == 19


# ------------------------------------------------------------------------------------------------ CLI: install / status
def test_cli_install_status(license_env, machine, tmp_path, capsys):
    license_env.clear()
    out = tmp_path / "alice.md20license"
    out.write_text(json.dumps(license_env.issue("Alice 王", days=7, machines=[machine]), ensure_ascii=False), encoding="utf-8")
    assert cli.main(["license", "install", f'"{out}"']) == 0              # drag-and-drop adds quotes
    assert cli.main(["license", "status"]) == 0
    assert "Alice 王" in capsys.readouterr().out
    other = tmp_path / "other.md20license"
    other.write_text(json.dumps(license_env.issue("Bob", machines=["1111-2222-3333-4444"])), encoding="utf-8")
    assert cli.main(["license", "install", str(other)]) == 1              # bound to another computer: not installed
    assert cli.main(["license", "install", str(tmp_path / "missing.md20license")]) == 1


# ------------------------------------------------------------------------------------------------ D-127: verification only
SIGNING_NAMES = ("sign_payload", "issue", "issue_batch", "make_payload", "write_license", "read_batch_csv", "load_private_key", "_pss")


def test_the_product_has_no_signing_api():
    for name in SIGNING_NAMES:
        assert not hasattr(L, name), name
    src = Path(L.__file__).read_text(encoding="utf-8")
    assert ".sign(" not in src and "load_pem_private_key" not in src and "generate_private_key" not in src
    assert not hasattr(stamp, "keygen")


def test_cli_has_no_issue_commands(capsys):
    for sub in (["license", "issue", "--key", "k.pem", "--name", "A"], ["license", "issue-batch", "--key", "k.pem", "--csv", "l.csv", "--out", "o"]):
        with pytest.raises(SystemExit):
            cli.main(sub)
    assert cli.main(["--dir", ".", "stamp", "keygen"]) == 1
    out = capsys.readouterr().out
    assert "私人工具" in out and "private signing tool" in out


def test_no_owner_tools_ship_with_the_package():
    root = Path(__file__).resolve().parent.parent
    assert not (root / "installer" / "owner").exists()
    for f in ("install.ps1", "install.sh"):
        text = (root / "installer" / f).read_text(encoding="utf-8")
        assert "installer/owner" not in text.replace("\\", "/") and "Issue-License" not in text
    assert not any(p for p in (root / "installer").rglob("*") if "Issue-License" in p.name or "Unlock-This-PC" in p.name)


# ------------------------------------------------------------------------------------------------ stamp
def test_stamp_records_the_licence_id_and_licensee(license_env):
    rec = stamp.stamp_record()
    assert rec["lic"]["who"] == "pytest" and len(rec["lic"]["id"]) == 16
    license_env.clear()
    assert "lic" not in stamp.stamp_record()
    doc = license_env.issue("Zed")
    license_env.put(doc)
    assert stamp.stamp_record()["lic"] == {"id": doc["payload"]["id"], "who": "Zed"}


def test_stamp_blob_carries_the_licence_id_for_the_owner(license_env, tmp_path, monkeypatch):
    priv, pub = K.stamp_keygen(tmp_path / "k")
    monkeypatch.setattr(stamp, "_PUB", pub)
    stamp.provenance_blob.cache_clear()
    license_env.clear()
    doc = license_env.issue("Zed"); license_env.put(doc)
    stamp.provenance_blob.cache_clear()
    rec = stamp.decrypt_blob(stamp.provenance_blob(), priv)
    assert rec["lid"] == doc["payload"]["id"]
    stamp.provenance_blob.cache_clear()


def test_machine_code_shape_is_stable_and_has_no_plain_text():
    L.machine_code.cache_clear()
    a = L.machine_code()
    assert a == L.machine_code() and len(a) == 19 and a.count("-") == 3
    import platform
    assert platform.node().upper() not in a
    assert L.normalize_machine(a.lower()) == a
