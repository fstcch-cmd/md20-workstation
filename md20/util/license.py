"""Signed licence for MD20 (D-125): the owner signs a licence file with a private key only the owner holds; a student
imports it, and the real calculations (docking, building, MD, binding free energy, folding) run only with a valid one.

A licence file ``*.md20license`` is JSON::

    {"payload": {"schema", "id", "licensee", "issued_at", "expires", "machines", "scope", "note", "issuer"},
     "sig": base64 RSA-PSS (SHA-256, MGF1-SHA256, maximum salt) over  DOMAIN + canonical JSON of the payload}

The program verifies it with the owner public key shipped in the package (``owner_pub.pem``, the same key pair the
provenance stamp uses; see D-125 for why one RSA key serves OAEP encryption and PSS signing).

Honest limits (also in docs/specs/licensing.md): the source is public, so a person who edits this file or the callers
can remove the check.  The layer is a threshold and evidence, not copy protection: removing it is a breach of the
licence terms, and every output carries the licence id (``stamp_record``).

NOTHING here can be switched off from outside the process: no environment variable, config file or command-line
option changes the trusted keys, the verification result or whether the check runs.  A published back door would tell
everybody how to get around the check.  Tests change ``TRUSTED_KEYS`` (a module attribute) with pytest's monkeypatch.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import platform
import re
import secrets
import sys
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..i18n import LANGS, pick
from .paths import app_data_dir

SCHEMA = "md20-license/1"
EXT = ".md20license"
DOMAIN = b"md20-license-v1\n"                 # domain separation: a signature over anything else never verifies as a licence
ISSUER = "HCC Lab, NKUST"
SCOPES = ("use", "all")
MAX_FILE_BYTES = 64 * 1024
CONTACT = "HCC Lab, NKUST"

_PUB = Path(__file__).with_name("owner_pub.pem")
# Public keys the program trusts, as PEM bytes.  A second key can be added here when the owner changes keys (the old
# key stays until every licence signed with it has expired).  Only the owner's key ships; do not read this from
# the environment or a file outside the package.
TRUSTED_KEYS: list[bytes] = [_PUB.read_bytes()] if _PUB.is_file() else []
# Licences that ship inside the package (empty today).  If the owner ever opens the program to everybody, one signed
# ``scope: all`` file placed here is enough; it still has to carry the owner's signature.
BUNDLED_DIR = Path(__file__).with_name("licenses")

VALID, EXPIRED, WRONG_MACHINE, BAD_SIGNATURE, NONE = "valid", "expired", "wrong_machine", "bad_signature", "none"
_RANK = {VALID: 0, EXPIRED: 1, WRONG_MACHINE: 2, BAD_SIGNATURE: 3, NONE: 4}        # which file to report when none is valid

LANG_ORDER = ("zh", "en", "ja", "ko")


# ---------------------------------------------------------------------------------------------- texts (zh, en, ja, ko)
TEXT = {
    VALID: ("授權有效：{licensee}，期限 {expires}。",
            "Licence valid: {licensee}, until {expires}.",
            "ライセンスは有効です。{licensee}、期限は {expires} です。",
            "라이선스가 유효합니다. {licensee}, 만료일 {expires}."),
    EXPIRED: ("授權已過期（{expires}）。",
              "The licence expired on {expires}.",
              "ライセンスの期限が切れています（{expires}）。",
              "라이선스가 만료되었습니다({expires})."),
    WRONG_MACHINE: ("這份授權綁定其他電腦，不能在這台電腦使用。",
                    "This licence is bound to another computer and cannot be used on this one.",
                    "このライセンスは別のパソコンに紐づいているため、このパソコンでは使えません。",
                    "이 라이선스는 다른 컴퓨터에 묶여 있어 이 컴퓨터에서는 쓸 수 없습니다."),
    BAD_SIGNATURE: ("授權檔的簽章不正確（檔案被改過、損毀，或不是 HCC Lab 簽發）。",
                    "The signature of the licence file is not valid (the file was changed or damaged, or HCC Lab did not issue it).",
                    "ライセンスファイルの署名が正しくありません（改変・破損、または HCC Lab が発行したものではありません）。",
                    "라이선스 파일의 서명이 올바르지 않습니다(파일이 바뀌었거나 손상되었거나 HCC Lab이 발급한 것이 아닙니다)."),
    NONE: ("這台電腦還沒有 MD20 授權，所以不能做真正的計算。",
           "This computer has no MD20 licence yet, so real calculations are blocked.",
           "このパソコンにはまだ MD20 のライセンスがないため、実際の計算はできません。",
           "이 컴퓨터에는 아직 MD20 라이선스가 없어 실제 계산을 할 수 없습니다."),
}
HOWTO = ("請向 HCC Lab 申請授權檔（.md20license），申請時把下面的機器碼寄給老師。收到檔案後，雙擊 MD20-Unlock，"
         "或在命令列執行 md20 license install 檔名。查看與診斷（doctor、demo、報告）不需要授權。",
         "Ask HCC Lab for a licence file (.md20license) and send your instructor the machine code below. When you "
         "have the file, double-click MD20-Unlock, or run md20 license install FILE on the command line. Viewing and "
         "diagnostics (doctor, demo, reports) do not need a licence.",
         "HCC Lab にライセンスファイル（.md20license）を申請し、下のマシンコードを先生に送ってください。ファイルを受け取ったら、"
         "MD20-Unlock をダブルクリックするか、コマンドラインで md20 license install ファイル名 を実行します。"
         "表示と診断（doctor、demo、レポート）にはライセンスは要りません。",
         "HCC Lab에 라이선스 파일(.md20license)을 신청하고 아래 머신 코드를 교수님께 보내십시오. 파일을 받으면 MD20-Unlock을 "
         "더블클릭하거나 명령줄에서 md20 license install 파일명 을 실행합니다. 보기와 진단(doctor, demo, 보고서)에는 "
         "라이선스가 필요하지 않습니다.")
MACHINE_LABEL = ("本機機器碼", "Machine code of this computer", "このパソコンのマシンコード", "이 컴퓨터의 머신 코드")
INSTALLED = ("授權已安裝：{licensee}（期限 {expires}）。",
             "Licence installed: {licensee} (until {expires}).",
             "ライセンスをインストールしました。{licensee}（期限 {expires}）。",
             "라이선스를 설치했습니다. {licensee}(만료일 {expires}).")
NOT_INSTALLED = ("沒有安裝這份授權檔。",
                 "This licence file was not installed.",
                 "このライセンスファイルはインストールしませんでした。",
                 "이 라이선스 파일을 설치하지 않았습니다.")
NO_EXPIRY = ("沒有期限", "no expiry", "期限なし", "기한 없음")
ALL_MACHINES = ("所有電腦", "all computers", "すべてのパソコン", "모든 컴퓨터")
BLOCKED_SHORT = ("需要 MD20 授權才能做真正的計算。開啟「授權」說明並匯入授權檔。",
                 "A MD20 licence is needed for real calculations. Open the licence notice and import your licence file.",
                 "実際の計算には MD20 のライセンスが必要です。ライセンスの案内を開き、ライセンスファイルを取り込んでください。",
                 "실제 계산에는 MD20 라이선스가 필요합니다. 라이선스 안내를 열고 라이선스 파일을 가져오십시오.")


class LicenseError(Exception):
    """A licence file could not be read, signed or installed.  ``texts`` holds the (zh, en, ja, ko) message."""

    def __init__(self, texts, status: "LicenseStatus | None" = None):
        self.texts = texts if isinstance(texts, tuple) else (str(texts),) * 4
        self.status = status
        super().__init__(pick(self.texts, "en"))


class LicenseRequired(RuntimeError):
    """Raised at the start of a real calculation when there is no valid licence."""

    def __init__(self, status: "LicenseStatus"):
        self.status = status
        super().__init__(status.message("en"))

    def texts(self) -> tuple:
        return tuple(self.status.message(l, with_howto=True) for l in LANG_ORDER)


# ---------------------------------------------------------------------------------------------- machine code
def _raw_machine_id() -> str:
    """A stable per-installation id from the operating system, or ''.  It is only ever used inside a salted hash."""
    try:
        if sys.platform.startswith("win"):
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                                0, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)) as k:
                return str(winreg.QueryValueEx(k, "MachineGuid")[0])
        if sys.platform == "darwin":
            import subprocess
            out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True, text=True,
                                 timeout=5).stdout
            m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
            return m.group(1) if m else ""
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                v = Path(p).read_text(encoding="ascii", errors="ignore").strip()
                if v:
                    return v
            except OSError:
                continue
    except Exception:  # noqa: BLE001  (registry, ioreg or file missing: fall back to the host name)
        pass
    return ""


@lru_cache(maxsize=1)
def machine_code() -> str:
    """Short readable code of this computer, e.g. ``3F9A-07C2-B15D-6E48``: first 64 bits of a salted SHA-256 of the
    OS machine id (host name if there is none), the OS and the CPU architecture.  It contains no readable personal data
    and does not depend on the user account."""
    raw = f"{_raw_machine_id() or platform.node()}|{platform.system()}|{platform.machine()}"
    h = hashlib.sha256(("md20-license-machine|" + raw).encode("utf-8")).hexdigest()[:16].upper()
    return "-".join(h[i:i + 4] for i in range(0, 16, 4))


def normalize_machine(code: str) -> str:
    """16 hex characters in canonical grouping, or raise ValueError."""
    h = re.sub(r"[\s\-]", "", str(code or "")).upper()
    if not re.fullmatch(r"[0-9A-F]{16}", h):
        raise ValueError(f"machine code must be 16 hexadecimal characters (like 3F9A-07C2-B15D-6E48): {code!r}")
    return "-".join(h[i:i + 4] for i in range(0, 16, 4))


# ---------------------------------------------------------------------------------------------- canonical JSON, signing
def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _pss():
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    return padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256()


def _verify_with(pub_pem: bytes, message: bytes, sig: bytes) -> bool:
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        key = serialization.load_pem_public_key(pub_pem)
        if not isinstance(key, rsa.RSAPublicKey):
            return False
        key.verify(sig, message, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.AUTO), hashes.SHA256())
        return True
    except Exception:  # noqa: BLE001  (InvalidSignature, bad PEM, missing library: all mean "not verified")
        return False


def signature_ok(doc: dict) -> bool:
    """True when ``doc['sig']`` is a valid signature of ``doc['payload']`` by one of TRUSTED_KEYS."""
    try:
        message = DOMAIN + canonical(doc["payload"])
        sig = base64.b64decode(doc["sig"], validate=True)
    except Exception:  # noqa: BLE001
        return False
    return any(_verify_with(k, message, sig) for k in list(TRUSTED_KEYS))


def load_private_key(path, password: bytes | None = None):
    """Read a PEM private key.  An encrypted key asks for its password on the terminal (never from the environment)."""
    from cryptography.hazmat.primitives import serialization
    data = Path(path).read_bytes()
    try:
        return serialization.load_pem_private_key(data, password=password)
    except TypeError:
        if not sys.stdin or not sys.stdin.isatty():
            raise LicenseError(("私鑰有密碼，但這裡無法輸入密碼。", "The private key is password protected and no terminal is available to ask for it.",
                                "秘密鍵にパスワードがありますが、入力できる端末がありません。",
                                "개인 키에 암호가 있지만 암호를 입력할 터미널이 없습니다."))
        import getpass
        return serialization.load_pem_private_key(data, password=getpass.getpass("Private key password: ").encode())


def _today() -> dt.date:
    return dt.date.today()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def make_payload(licensee: str, *, expires: str | None = None, days: int | None = None, machines=(), scope: str = "use",
                 note: str = "") -> dict:
    """Validated payload dict (not yet signed).  ``days`` counts from today; ``expires`` is an ISO date, last valid day."""
    licensee = str(licensee or "").strip()
    if not licensee:
        raise LicenseError(("需要被授權人的姓名。", "The licensee name is required.", "ライセンスを受ける人の名前が必要です。", "라이선스를 받는 사람의 이름이 필요합니다."))
    if scope not in SCOPES:
        raise LicenseError((f"scope 必須是 {SCOPES}。",) * 4)
    if days is not None and expires:
        raise LicenseError(("--days 與 --expires 只能選一個。", "Use either --days or --expires, not both.",
                            "--days と --expires はどちらか一方だけ指定してください。", "--days와 --expires 중 하나만 지정하십시오."))
    if days is not None:
        if int(days) < 1:
            raise LicenseError(("天數必須是正整數。", "Days must be a positive integer.", "日数は正の整数にしてください。", "일수는 양의 정수여야 합니다."))
        expires = (_today() + dt.timedelta(days=int(days))).isoformat()
    if expires:
        try:
            expires = dt.date.fromisoformat(str(expires)).isoformat()
        except ValueError:
            raise LicenseError((f"日期格式要 YYYY-MM-DD：{expires}", f"Date format must be YYYY-MM-DD: {expires}",
                                f"日付は YYYY-MM-DD の形式にしてください：{expires}", f"날짜 형식은 YYYY-MM-DD여야 합니다: {expires}")) from None
    else:
        expires = None
    try:
        mach = sorted({normalize_machine(m) for m in (machines or ()) if str(m).strip()})
    except ValueError as exc:
        raise LicenseError((f"機器碼格式不對（16 個十六進位字元，如 3F9A-07C2-B15D-6E48）：{exc.args[0].rsplit(': ', 1)[-1]}",
                            f"Bad machine code (16 hexadecimal characters, like 3F9A-07C2-B15D-6E48): {exc.args[0].rsplit(': ', 1)[-1]}",
                            f"マシンコードの形式が正しくありません（16 桁の 16 進数、例 3F9A-07C2-B15D-6E48）：{exc.args[0].rsplit(': ', 1)[-1]}",
                            f"머신 코드 형식이 올바르지 않습니다(16자리 16진수, 예 3F9A-07C2-B15D-6E48): {exc.args[0].rsplit(': ', 1)[-1]}")) from None
    if scope == "all" and mach:
        raise LicenseError(("scope all 不綁機器，不能同時指定機器碼。", "Scope all is not bound to machines; do not give machine codes.",
                            "scope all はマシンに紐づけないため、マシンコードは指定できません。", "scope all은 컴퓨터에 묶지 않으므로 머신 코드를 지정할 수 없습니다."))
    return {"schema": SCHEMA, "id": secrets.token_hex(8), "licensee": licensee, "issued_at": _now_iso(), "expires": expires,
            "machines": mach, "scope": scope, "note": str(note or ""), "issuer": ISSUER}


def sign_payload(payload: dict, private_key) -> dict:
    """Sign with the owner's private key (an object from load_private_key) and check that this program would accept it."""
    pad, algo = _pss()
    sig = private_key.sign(DOMAIN + canonical(payload), pad, algo)
    doc = {"payload": payload, "sig": base64.b64encode(sig).decode("ascii")}
    if not signature_ok(doc):
        raise LicenseError(("這把私鑰不是本程式信任的擁有者金鑰（公鑰不符），簽出的授權檔不會被接受。",
                            "This private key does not match a public key this program trusts; the licence it signs would be rejected.",
                            "この秘密鍵は本プログラムが信頼する所有者の公開鍵と一致しません。署名したライセンスは受け付けられません。",
                            "이 개인 키는 이 프로그램이 신뢰하는 소유자 공개 키와 맞지 않습니다. 서명한 라이선스는 거부됩니다."))
    return doc


def write_license(doc: dict, out: Path | str) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def issue(key_path, licensee: str, *, out: Path | str | None = None, password: bytes | None = None, key=None, **kw) -> tuple[Path, dict]:
    """Owner side: read the private key (read only), sign, write ``<out>`` (default ``<name>.md20license`` here)."""
    payload = make_payload(licensee, **kw)
    doc = sign_payload(payload, key if key is not None else load_private_key(key_path, password))
    if out is None:
        from .paths import safe_name
        out = Path.cwd() / (safe_name(licensee) + EXT)
    return write_license(doc, out), payload


def read_batch_csv(path) -> list[dict]:
    """Rows of ``name, days-or-date, machine code (optional)``.  A header row (second cell neither a number nor a date)
    is skipped.  UTF-8, with or without BOM (Excel writes one)."""
    import csv
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for n, r in enumerate(csv.reader(fh), 1):
            cells = [c.strip() for c in r]
            if not any(cells):
                continue
            name, term, mach = (cells + ["", "", ""])[:3]
            if n == 1 and term and not re.fullmatch(r"\d+", term) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", term):
                continue
            if not name:
                raise LicenseError((f"第 {n} 列沒有姓名。", f"Row {n} has no name.", f"{n} 行目に名前がありません。", f"{n}행에 이름이 없습니다."))
            row = {"name": name, "machine": mach}
            if re.fullmatch(r"\d+", term):
                row["days"] = int(term)
            elif term:
                row["expires"] = term
            rows.append(row)
    return rows


def issue_batch(key_path, csv_path, out_dir, *, password: bytes | None = None, scope: str = "use", note: str = "") -> list[dict]:
    from .paths import safe_name
    key = load_private_key(key_path, password)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    done, used = [], set()
    # every row is checked before anything is written: a bad row must not leave half a batch behind
    prepared = [(row, make_payload(row["name"], days=row.get("days"), expires=row.get("expires"),
                                   machines=[row["machine"]] if row.get("machine") else (), scope=scope, note=note))
                for row in read_batch_csv(csv_path)]
    for row, payload in prepared:
        base = safe_name(row["name"]); name = base
        k = 1
        while name.lower() in used:
            k += 1; name = f"{base}_{k}"
        used.add(name.lower())
        path = write_license(sign_payload(payload, key), out_dir / (name + EXT))
        done.append({"name": row["name"], "id": payload["id"], "expires": payload["expires"], "machines": payload["machines"],
                     "file": str(path)})
    if done:
        import csv
        with open(out_dir / "issued.csv", "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["name", "id", "expires", "machine", "file"])
            for d in done:
                w.writerow([d["name"], d["id"], d["expires"] or "", " ".join(d["machines"]), Path(d["file"]).name])
    return done


# ---------------------------------------------------------------------------------------------- status
@dataclass
class LicenseStatus:
    state: str
    licensee: str = ""
    license_id: str = ""
    expires: str | None = None
    scope: str = ""
    machines: list = field(default_factory=list)
    path: str = ""
    machine_code: str = ""
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.state == VALID

    def message(self, lang: str = "en", *, with_howto: bool = False) -> str:
        """The state in one language; with ``with_howto`` the request instructions and the machine code follow."""
        exp = pick(NO_EXPIRY, lang) if not self.expires else self.expires
        text = pick(TEXT[self.state], lang).format(licensee=self.licensee, expires=exp)
        if with_howto and not self.ok:
            text += "\n" + pick(HOWTO, lang) + "\n" + pick(MACHINE_LABEL, lang) + ": " + self.machine_code
        return text

    def message_all(self, *, with_howto: bool = False) -> str:
        return "\n\n".join(self.message(l, with_howto=with_howto) for l in LANG_ORDER)

    def summary(self) -> dict:
        return {"state": self.state, "licensee": self.licensee, "id": self.license_id, "expires": self.expires,
                "scope": self.scope, "machine_code": self.machine_code}


def license_dir() -> Path:
    return app_data_dir() / "license"


def search_dirs() -> list[Path]:
    return [license_dir(), BUNDLED_DIR]


def evaluate(doc: object, *, source: str = "") -> LicenseStatus:
    """Judge one parsed licence document for THIS computer and today."""
    mc = machine_code()
    if not isinstance(doc, dict) or not isinstance(doc.get("payload"), dict) or not isinstance(doc.get("sig"), str):
        return LicenseStatus(BAD_SIGNATURE, path=source, machine_code=mc, detail="not a licence document")
    p = doc["payload"]
    if not signature_ok(doc):
        return LicenseStatus(BAD_SIGNATURE, path=source, machine_code=mc, detail="signature does not verify")
    # the signature is genuine: from here on the payload is trusted, but a malformed one is still rejected
    try:
        if p.get("schema") != SCHEMA or p.get("scope") not in SCOPES:
            raise ValueError("schema or scope")
        lic, lid = str(p["licensee"]), str(p["id"])
        exp = p.get("expires")
        exp_date = dt.date.fromisoformat(exp) if exp else None
        machines = [normalize_machine(m) for m in (p.get("machines") or [])]
    except Exception as exc:  # noqa: BLE001
        return LicenseStatus(BAD_SIGNATURE, path=source, machine_code=mc, detail=f"payload malformed: {exc}")
    st = LicenseStatus(VALID, licensee=lic, license_id=lid, expires=exp, scope=p["scope"], machines=machines, path=source, machine_code=mc)
    if exp_date is not None and _today() > exp_date:
        st.state = EXPIRED
    elif p["scope"] != "all" and machines and mc not in machines:
        st.state = WRONG_MACHINE
    return st


def parse_text(text: str) -> dict:
    if len(text.encode("utf-8", errors="ignore")) > MAX_FILE_BYTES:
        raise LicenseError(("授權檔太大，不像是授權檔。", "The file is too large to be a licence file.", "ファイルが大きすぎてライセンスファイルとは思えません。",
                            "파일이 너무 커서 라이선스 파일이 아닌 것 같습니다."))
    try:
        doc = json.loads(text)
    except ValueError:
        raise LicenseError(("這不是授權檔（不是 JSON）。", "This is not a licence file (not JSON).", "ライセンスファイルではありません（JSON ではありません）。",
                            "라이선스 파일이 아닙니다(JSON이 아님).")) from None
    return doc


def read_file(path) -> dict:
    p = Path(path)
    try:
        if p.stat().st_size > MAX_FILE_BYTES:
            raise LicenseError(("授權檔太大，不像是授權檔。", "The file is too large to be a licence file.", "ファイルが大きすぎてライセンスファイルとは思えません。",
                                "파일이 너무 커서 라이선스 파일이 아닌 것 같습니다."))
        return parse_text(p.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise LicenseError((f"讀不到檔案：{p}（{exc.__class__.__name__}）", f"Cannot read the file: {p} ({exc.__class__.__name__})",
                            f"ファイルを読めません：{p}（{exc.__class__.__name__}）", f"파일을 읽을 수 없습니다: {p} ({exc.__class__.__name__})")) from exc
    except UnicodeDecodeError as exc:
        raise LicenseError(("這不是授權檔（不是文字檔）。", "This is not a licence file (not text).", "ライセンスファイルではありません（テキストではありません）。",
                            "라이선스 파일이 아닙니다(텍스트가 아님).")) from exc


_cache: dict = {"key": None, "status": None}


def _reset_cache() -> None:
    _cache["key"] = _cache["status"] = None
    _stamp_cache["t"] = 0.0
    _stamp_cache["v"] = None


def _files() -> list[Path]:
    out = []
    for d in search_dirs():
        try:
            out += sorted(p for p in Path(d).glob("*" + EXT) if p.is_file())
        except OSError:
            continue
    return out


def status() -> LicenseStatus:
    """The best licence found for this computer: any valid one wins; otherwise the most informative failure."""
    files = _files()
    sig = []
    for f in files:
        try:
            s = f.stat()
            sig.append((str(f), s.st_mtime_ns, s.st_size))
        except OSError:
            continue
    key = (tuple(sig), tuple(TRUSTED_KEYS), _today(), machine_code())
    if _cache["key"] == key and _cache["status"] is not None:
        return _cache["status"]
    best = LicenseStatus(NONE, machine_code=machine_code())
    for f in files:
        try:
            st = evaluate(read_file(f), source=str(f))
        except LicenseError:
            st = LicenseStatus(BAD_SIGNATURE, path=str(f), machine_code=machine_code(), detail="unreadable")
        if _RANK[st.state] < _RANK[best.state]:
            best = st
        if best.ok:
            break
    _cache["key"], _cache["status"] = key, best
    return best


def require(what: str = "") -> LicenseStatus:
    """Call at the start of every real calculation.  ``what`` is only for readability at the call site."""
    st = status()
    if not st.ok:
        raise LicenseRequired(st)
    return st


def install(path) -> LicenseStatus:
    """Student side: copy a licence file into the per-user licence folder, but only when it is valid for this computer."""
    doc = read_file(path)
    st = evaluate(doc, source=str(path))
    if not st.ok:
        raise LicenseError(tuple(st.message(l, with_howto=(st.state in (WRONG_MACHINE, EXPIRED))) + "\n" + pick(NOT_INSTALLED, l)
                                 for l in LANG_ORDER), st)
    d = license_dir()
    d.mkdir(parents=True, exist_ok=True)
    dest = d / (st.license_id + EXT)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, dest)
    st.path = str(dest)
    _reset_cache()
    try:
        from .stamp import provenance_blob
        provenance_blob.cache_clear()
    except Exception:  # noqa: BLE001
        pass
    return st


def installed_message(st: LicenseStatus) -> str:
    return "\n\n".join(pick(INSTALLED, l).format(licensee=st.licensee, expires=st.expires or pick(NO_EXPIRY, l)) for l in LANG_ORDER)


# ---------------------------------------------------------------------------------------------- for the provenance stamp
_stamp_cache: dict = {"t": 0.0, "v": None}


def stamp_info() -> dict | None:
    """``{"id", "who"}`` of the valid licence in use, or None.  Cached for a minute (atomic_write_json calls this on every
    JSON file it writes)."""
    now = time.monotonic()
    if _stamp_cache["v"] is not None and now - _stamp_cache["t"] < 60 and _stamp_cache.get("k") == tuple(TRUSTED_KEYS):
        return _stamp_cache["v"] or None
    try:
        st = status()
    except Exception:  # noqa: BLE001  (the stamp must never break a write)
        return None
    v = {"id": st.license_id, "who": st.licensee} if st.ok else {}
    _stamp_cache.update(t=now, v=v, k=tuple(TRUSTED_KEYS))
    return v or None
