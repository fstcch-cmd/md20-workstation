"""Signed licence for MD20 (D-125, D-127): the owner signs a licence file with a private key only the owner holds; a student
imports it, and the real calculations (docking, building, MD, binding free energy, folding) run only with a valid one.
This module only VERIFIES.  Issuing licences (key generation, signing, the registry) lives in the owner's private repository
(D-127); the file format is specified in docs/specs/licensing.md and pinned by tests/data/license_vector_v1.json.

A licence file ``*.md20license`` is JSON::

    {"payload": {"schema", "id", "licensee", "issued_at", "expires", "machines", "scope", "note", "issuer"
                 [, "tier", "features", "org", "seats", "max_version", "issuer_key"  -- schema md20-license-v2 only, all optional]},
     "sig": base64 RSA-PSS (SHA-256, MGF1-SHA256, maximum salt) over  DOMAIN + canonical JSON of the payload}

Format v1 (``md20-license/1``, domain ``md20-license-v1``) and v2 (``md20-license-v2``, domain ``md20-license-v2``) are both
accepted (D-128).  A missing v2 field behaves like v1: every feature, any tier, no seat or version limit.  The owner can also
sign a revocation list (``revoked.json``, domain ``md20-revocations-v1``) that makes listed licence ids invalid.

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
import sys
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..i18n import LANGS, pick
from .paths import app_data_dir

SCHEMA = "md20-license/1"                    # format v1
SCHEMA_V2 = "md20-license-v2"                # format v2 (D-128): optional tier, features, org, seats, max_version, issuer_key
SCHEMAS = (SCHEMA, SCHEMA_V2)
EXT = ".md20license"
DOMAIN = b"md20-license-v1\n"                 # domain separation: a signature over anything else never verifies as a licence
DOMAIN_V2 = b"md20-license-v2\n"              # v2 licences are signed under their own prefix (a v1 signature never makes a v2 licence)
REV_SCHEMA = "md20-revocations-v1"
REV_DOMAIN = b"md20-revocations-v1\n"         # a revocation list is never a licence and a licence is never a revocation list
REV_NAME = "revoked.json"
SCOPES = ("use", "all")
TIERS = ("teaching", "research", "evaluation", "commercial", "site")
FEATURES = ("binding", "membrane", "hts", "cg")      # gateable features; a licence without `features` (or with "all") has all of them
MAX_FILE_BYTES = 64 * 1024
MAX_REV_BYTES = 1024 * 1024
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
REVOKED, VERSION_LIMIT = "revoked", "version_limit"                                  # D-128
# which file to report when none is valid
_RANK = {VALID: 0, EXPIRED: 1, VERSION_LIMIT: 2, WRONG_MACHINE: 3, REVOKED: 4, BAD_SIGNATURE: 5, NONE: 6}

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
    REVOKED: ("這份授權已被 HCC Lab 撤銷，不能再使用。如有疑問請聯絡 HCC Lab。",
              "This licence has been revoked by HCC Lab and can no longer be used. Contact HCC Lab if you have questions.",
              "このライセンスは HCC Lab により失効させられており、使用できません。ご不明な点は HCC Lab にお問い合わせください。",
              "이 라이선스는 HCC Lab이 철회하여 더 이상 사용할 수 없습니다. 문의 사항은 HCC Lab에 연락하십시오."),
    VERSION_LIMIT: ("這份授權只涵蓋 MD20 {max_version} 以前的版本，目前版本是 {version}。請向 HCC Lab 更新維護授權，或改用較舊的版本。",
                    "This licence covers MD20 versions up to {max_version}; this is version {version}. Ask HCC Lab to renew maintenance, or use an older version.",
                    "このライセンスは MD20 {max_version} までのバージョンが対象です。現在のバージョンは {version} です。HCC Lab に保守の更新を依頼するか、古いバージョンをお使いください。",
                    "이 라이선스는 MD20 {max_version} 이하 버전만 적용됩니다. 현재 버전은 {version}입니다. HCC Lab에 유지보수 갱신을 요청하거나 이전 버전을 사용하십시오."),
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


FEATURE_NAMES = {
    "binding": ("結合自由能（SMD／傘狀採樣）", "binding free energy (SMD / umbrella sampling)", "結合自由エネルギー（SMD／アンブレラサンプリング）",
                "결합 자유 에너지(SMD/엄브렐라 샘플링)"),
    "membrane": ("膜系統", "membrane systems", "膜系", "막 시스템"),
    "hts": ("HTS 篩選", "HTS screening", "HTS スクリーニング", "HTS 스크리닝"),
    "cg": ("粗粒化模擬", "coarse-grained simulation", "粗視化シミュレーション", "조립화(coarse-grained) 시뮬레이션"),
}
NO_FEATURE = ("你的授權不含「{name}」功能（{feature}）。目前授權等級：{tier}；包含的功能：{have}。如需此功能，請向 HCC Lab 申請升級授權。",
              "Your licence does not include {name} ({feature}). Licence tier: {tier}; features included: {have}. To use it, ask HCC Lab for an upgraded licence.",
              "お持ちのライセンスには「{name}」（{feature}）が含まれていません。ライセンスの区分：{tier}、含まれる機能：{have}。ご利用には HCC Lab にアップグレードを申請してください。",
              "귀하의 라이선스에는 '{name}'({feature}) 기능이 포함되어 있지 않습니다. 라이선스 등급: {tier}, 포함된 기능: {have}. 사용하려면 HCC Lab에 업그레이드를 신청하십시오.")
ALL_FEATURES = ("全部功能", "all features", "すべての機能", "모든 기능")
REV_INSTALLED = ("撤銷清單已更新（{issued_at}，共 {n} 個授權編號）。",
                 "Revocation list updated ({issued_at}, {n} licence ids).",
                 "失効リストを更新しました（{issued_at}、ライセンス ID {n} 件）。",
                 "철회 목록을 갱신했습니다({issued_at}, 라이선스 ID {n}개).")
REV_NOT_NEWER = ("這份撤銷清單不比目前使用的新（目前 {current}，這份 {new}），沒有更新。為了防止退回舊清單，只接受較新的。",
                 "This revocation list is not newer than the one in use (current {current}, this one {new}); nothing changed. Only newer lists are accepted so that an old list cannot be put back.",
                 "この失効リストは現在使用中のものより新しくありません（現在 {current}、このファイル {new}）。変更しませんでした。古いリストに戻されないよう、新しいものだけを受け付けます。",
                 "이 철회 목록은 현재 사용 중인 것보다 새롭지 않습니다(현재 {current}, 이 파일 {new}). 변경하지 않았습니다. 오래된 목록으로 되돌리는 것을 막기 위해 더 새로운 것만 받습니다.")
REV_BAD = ("這不是有效的撤銷清單（簽章不正確、格式不對，或不是 HCC Lab 簽發）。",
           "This is not a valid revocation list (bad signature or format, or HCC Lab did not issue it).",
           "有効な失効リストではありません（署名・形式が正しくない、または HCC Lab が発行したものではありません）。",
           "유효한 철회 목록이 아닙니다(서명이나 형식이 올바르지 않거나 HCC Lab이 발급한 것이 아닙니다).")


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


class FeatureNotLicensed(LicenseRequired):
    """D-128: the licence is valid but does not include the feature this calculation needs.  The CLI ends with the same
    exit code as a missing licence (13); the GUI shows the message on a card.  ``texts()`` is (zh, en, ja, ko)."""

    def __init__(self, status: "LicenseStatus", feature: str):
        self.status, self.feature = status, feature
        RuntimeError.__init__(self, pick(self.texts(), "en"))

    def texts(self) -> tuple:
        return feature_denied_texts(self.status, self.feature)


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


# ---------------------------------------------------------------------------------------------- canonical JSON, verification
def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


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


def key_fingerprint(pub_pem: bytes) -> str:
    """SHA-256 of the DER SubjectPublicKeyInfo, 64 lowercase hex characters ('' when the PEM cannot be read)."""
    try:
        from cryptography.hazmat.primitives import serialization
        key = serialization.load_pem_public_key(pub_pem)
        return hashlib.sha256(key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
    except Exception:  # noqa: BLE001
        return ""


def _domain_for(payload: object) -> bytes:
    """The signing prefix that belongs to the payload's own schema: a v2 payload only verifies under the v2 prefix and a v1
    payload only under the v1 prefix, so neither can be passed off as the other."""
    return DOMAIN_V2 if isinstance(payload, dict) and payload.get("schema") == SCHEMA_V2 else DOMAIN


def _signer(message: bytes, sig: bytes) -> bytes | None:
    for k in list(TRUSTED_KEYS):
        if _verify_with(k, message, sig):
            return k
    return None


def signing_key(doc: dict) -> bytes | None:
    """The trusted public key (PEM) whose signature ``doc['sig']`` is over ``doc['payload']``, else None."""
    try:
        message = _domain_for(doc["payload"]) + canonical(doc["payload"])
        sig = base64.b64decode(doc["sig"], validate=True)
    except Exception:  # noqa: BLE001
        return None
    return _signer(message, sig)


def signature_ok(doc: dict) -> bool:
    """True when ``doc['sig']`` is a valid signature of ``doc['payload']`` by one of TRUSTED_KEYS."""
    return signing_key(doc) is not None


def _today() -> dt.date:
    return dt.date.today()


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
    # D-128 (format v2); all empty / None for a v1 licence, which behaves as "every feature, no limits"
    schema: str = ""
    tier: str = ""
    features: list | None = None          # None = every feature
    org: str = ""
    seats: int | None = None
    max_version: str | None = None

    @property
    def ok(self) -> bool:
        return self.state == VALID

    def allows(self, feature: str) -> bool:
        return self.features is None or feature in self.features

    def message(self, lang: str = "en", *, with_howto: bool = False) -> str:
        """The state in one language; with ``with_howto`` the request instructions and the machine code follow."""
        exp = pick(NO_EXPIRY, lang) if not self.expires else self.expires
        text = pick(TEXT[self.state], lang).format(licensee=self.licensee, expires=exp, max_version=self.max_version or "-",
                                                   version=_app_version())
        if with_howto and not self.ok:
            text += "\n" + pick(HOWTO, lang) + "\n" + pick(MACHINE_LABEL, lang) + ": " + self.machine_code
        return text

    def message_all(self, *, with_howto: bool = False) -> str:
        return "\n\n".join(self.message(l, with_howto=with_howto) for l in LANG_ORDER)

    def summary(self) -> dict:
        return {"state": self.state, "licensee": self.licensee, "id": self.license_id, "expires": self.expires,
                "scope": self.scope, "machine_code": self.machine_code, "schema": self.schema, "tier": self.tier,
                "features": "all" if self.features is None else list(self.features), "org": self.org, "seats": self.seats,
                "max_version": self.max_version}


def feature_denied_texts(st: "LicenseStatus", feature: str) -> tuple:
    """(zh, en, ja, ko) 'your licence does not include X'."""
    out = []
    for i, l in enumerate(LANG_ORDER):
        have = pick(ALL_FEATURES, l) if st.features is None else (", ".join(st.features) or "-")
        out.append(pick(NO_FEATURE, l).format(name=pick(FEATURE_NAMES[feature], l) if feature in FEATURE_NAMES else feature,
                                              feature=feature, tier=st.tier or "-", have=have))
    return tuple(out)


def _app_version() -> str:
    try:
        from .. import __version__
        return str(__version__)
    except Exception:  # noqa: BLE001
        return "?"


def license_dir() -> Path:
    return app_data_dir() / "license"


def search_dirs() -> list[Path]:
    return [license_dir(), BUNDLED_DIR]


# ---------------------------------------------------------------------------------------------- revocation list (D-128)
@dataclass
class Revocations:
    issued_at: str
    ids: frozenset
    source: str = ""


_ISSUED_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_ID_RE = re.compile(r"[0-9a-f]{16}")


def parse_revocations(doc: object, *, source: str = "") -> Revocations:
    """Check a revocation document and return it.  Raises ValueError unless the owner's signature (domain
    ``md20-revocations-v1``) verifies and the payload is well formed."""
    if not isinstance(doc, dict) or not isinstance(doc.get("payload"), dict) or not isinstance(doc.get("sig"), str):
        raise ValueError("not a revocation document")
    p = doc["payload"]
    try:
        sig = base64.b64decode(doc["sig"], validate=True)
        message = REV_DOMAIN + canonical(p)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("signature not decodable") from exc
    if _signer(message, sig) is None:
        raise ValueError("signature does not verify")
    issued, ids = p.get("issued_at"), p.get("ids")
    if p.get("schema") != REV_SCHEMA or not isinstance(issued, str) or not _ISSUED_RE.fullmatch(issued):
        raise ValueError("schema or issued_at")
    try:
        time.strptime(issued, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("issued_at is not a date") from exc
    if not isinstance(ids, list) or not all(isinstance(i, str) and _ID_RE.fullmatch(i) for i in ids):
        raise ValueError("ids")
    return Revocations(issued, frozenset(ids), source)


def revocation_paths() -> list[Path]:
    """The app-data copy (installed with ``md20 license update-revocations``) and the one shipped in the package."""
    return [license_dir() / REV_NAME, BUNDLED_DIR / REV_NAME]


def _read_revocation_file(path: Path) -> Revocations | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_REV_BYTES:
            return None
        return parse_revocations(json.loads(path.read_text(encoding="utf-8-sig")), source=str(path))
    except (OSError, ValueError):
        return None


def revocations() -> Revocations | None:
    """The newest valid revocation list among the two places (a list with a bad signature is ignored; an older list never
    overrides a newer one).  Lists issued at the same second are merged.  None when there is no valid list."""
    found = [r for r in (_read_revocation_file(p) for p in revocation_paths()) if r is not None]
    if not found:
        return None
    newest = max(r.issued_at for r in found)
    top = [r for r in found if r.issued_at == newest]
    return Revocations(newest, frozenset().union(*(r.ids for r in top)), top[0].source)


def update_revocations(path) -> Revocations:
    """Import a revocation list into the per-user licence folder.  Accepted only when the owner's signature verifies and
    ``issued_at`` is newer than the list in use (so an old list cannot be put back).  Raises LicenseError."""
    p = Path(path)
    try:
        if p.stat().st_size > MAX_REV_BYTES:
            raise ValueError("too large")
        doc = json.loads(p.read_text(encoding="utf-8-sig"))
        new = parse_revocations(doc, source=str(p))
    except OSError as exc:
        raise LicenseError((f"讀不到檔案：{p}（{exc.__class__.__name__}）", f"Cannot read the file: {p} ({exc.__class__.__name__})",
                            f"ファイルを読めません：{p}（{exc.__class__.__name__}）", f"파일을 읽을 수 없습니다: {p} ({exc.__class__.__name__})")) from exc
    except ValueError:
        raise LicenseError(REV_BAD) from None
    cur = revocations()
    if cur is not None and new.issued_at <= cur.issued_at:
        raise LicenseError(tuple(pick(REV_NOT_NEWER, l).format(current=cur.issued_at, new=new.issued_at) for l in LANG_ORDER))
    d = license_dir()
    d.mkdir(parents=True, exist_ok=True)
    dest = d / REV_NAME
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, dest)
    new.source = str(dest)
    _reset_cache()
    return new


def revocations_message(r: Revocations) -> str:
    return "\n\n".join(pick(REV_INSTALLED, l).format(issued_at=r.issued_at, n=len(r.ids)) for l in LANG_ORDER)


# ---------------------------------------------------------------------------------------------- v2 payload
def _version_obj(text: str):
    from packaging.version import Version          # PEP 440 (packaging is a hard dependency of matplotlib)
    return Version(text)


def _parse_v2(p: dict, signer: bytes, machines: list) -> dict:
    """The optional v2 fields, validated.  Raises ValueError.  A missing field means 'no restriction' (= v1 behaviour)."""
    tier = p.get("tier")
    if tier is not None and tier not in TIERS:
        raise ValueError(f"tier {tier!r}")
    features = p.get("features")
    if features is not None:
        if not isinstance(features, list) or not all(isinstance(f, str) and f.strip() for f in features):
            raise ValueError("features")
        norm = sorted({f.strip().lower() for f in features})
        features = None if "all" in norm else norm
    org = p.get("org")
    if org is not None and not isinstance(org, str):
        raise ValueError("org")
    seats = p.get("seats")
    if seats is not None and (isinstance(seats, bool) or not isinstance(seats, int) or seats < 1):
        raise ValueError("seats")
    if seats is not None and len(machines) > seats:
        raise ValueError("more machines than seats")
    max_version = p.get("max_version")
    if max_version is not None:
        if not isinstance(max_version, str):
            raise ValueError("max_version")
        _version_obj(max_version)
    issuer_key = p.get("issuer_key")
    if issuer_key is not None:
        if not isinstance(issuer_key, str) or not re.fullmatch(r"[0-9a-f]{64}", issuer_key):
            raise ValueError("issuer_key")
        if issuer_key != key_fingerprint(signer):
            raise ValueError("issuer_key does not match the signing key")
    if tier == "site":                     # a site licence is bound to the organisation, not to computers
        if not (org or "").strip():
            raise ValueError("site licence needs org")
        if machines:
            raise ValueError("site licence must not list machines")
    return {"tier": tier or "", "features": features, "org": (org or "").strip(), "seats": seats, "max_version": max_version}


def _too_new(max_version: str | None) -> bool:
    """True when this MD20 is newer than the licence's ``max_version`` (PEP 440).  An unreadable version blocks."""
    if not max_version:
        return False
    try:
        return _version_obj(_app_version()) > _version_obj(max_version)
    except Exception:  # noqa: BLE001
        return True


def evaluate(doc: object, *, source: str = "", revoked: "Revocations | None | bool" = False) -> LicenseStatus:
    """Judge one parsed licence document for THIS computer and today.  ``revoked`` is the revocation list to apply; the default
    (False) reads it from disk."""
    mc = machine_code()
    if not isinstance(doc, dict) or not isinstance(doc.get("payload"), dict) or not isinstance(doc.get("sig"), str):
        return LicenseStatus(BAD_SIGNATURE, path=source, machine_code=mc, detail="not a licence document")
    p = doc["payload"]
    signer = signing_key(doc)
    if signer is None:
        return LicenseStatus(BAD_SIGNATURE, path=source, machine_code=mc, detail="signature does not verify")
    # the signature is genuine: from here on the payload is trusted, but a malformed one is still rejected
    try:
        if p.get("schema") not in SCHEMAS or p.get("scope") not in SCOPES:
            raise ValueError("schema or scope")
        lic, lid = str(p["licensee"]), str(p["id"])
        exp = p.get("expires")
        exp_date = dt.date.fromisoformat(exp) if exp else None
        machines = [normalize_machine(m) for m in (p.get("machines") or [])]
        extra = _parse_v2(p, signer, machines) if p["schema"] == SCHEMA_V2 else {}
    except Exception as exc:  # noqa: BLE001
        return LicenseStatus(BAD_SIGNATURE, path=source, machine_code=mc, detail=f"payload malformed: {exc}")
    st = LicenseStatus(VALID, licensee=lic, license_id=lid, expires=exp, scope=p["scope"], machines=machines, path=source,
                       machine_code=mc, schema=p["schema"], **extra)
    rev = revocations() if revoked is False else revoked
    if rev is not None and lid in rev.ids:
        st.state = REVOKED
    elif exp_date is not None and _today() > exp_date:
        st.state = EXPIRED
    elif _too_new(st.max_version):
        st.state = VERSION_LIMIT
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
    _stamp_cache["tier"] = ""


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
    for rp in revocation_paths():
        try:
            rs = rp.stat()
            sig.append((str(rp), rs.st_mtime_ns, rs.st_size))
        except OSError:
            continue
    key = (tuple(sig), tuple(TRUSTED_KEYS), _today(), machine_code(), _app_version())
    if _cache["key"] == key and _cache["status"] is not None:
        return _cache["status"]
    best = LicenseStatus(NONE, machine_code=machine_code())
    rev = revocations()
    for f in files:
        try:
            st = evaluate(read_file(f), source=str(f), revoked=rev)
        except LicenseError:
            st = LicenseStatus(BAD_SIGNATURE, path=str(f), machine_code=machine_code(), detail="unreadable")
        if _RANK[st.state] < _RANK[best.state]:
            best = st
        if best.ok:
            break
    _cache["key"], _cache["status"] = key, best
    return best


def require(what: str = "", *, feature: str | None = None) -> LicenseStatus:
    """Call at the start of every real calculation.  ``what`` is only for readability at the call site.  With ``feature``
    (one of FEATURES) the licence must include that feature too, else FeatureNotLicensed (a LicenseRequired) is raised."""
    st = status()
    if not st.ok:
        raise LicenseRequired(st)
    if feature is not None:
        if feature not in FEATURES:
            raise ValueError(f"unknown feature {feature!r}")
        if not st.allows(feature):
            raise FeatureNotLicensed(st, feature)
    return st


def require_features(what: str, features) -> LicenseStatus:
    """``require`` for a set of features: the first one the licence does not include raises FeatureNotLicensed."""
    st = require(what)
    for f in sorted(set(features or ())):
        require(what, feature=f)
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
    _stamp_cache.update(t=now, v=v, k=tuple(TRUSTED_KEYS), tier=st.tier if st.ok else "")
    return v or None


def stamp_tier() -> str:
    """Tier of the valid licence in use ('' for none or a v1 licence); same cache as ``stamp_info``."""
    stamp_info()
    return _stamp_cache.get("tier", "") or ""
