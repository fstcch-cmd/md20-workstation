"""HCC Lab provenance stamp for every file MD20 writes.

Three layers
------------
1. Visible     "© HCC Lab, NKUST — MD20" in reports, figure metadata, PDB/SDF headers.
2. Hidden      markers in places users rarely look: PNG/SVG metadata keys, PDB ``REMARK 999``,
               SDF property, JSON ``_md20`` key, zero-width characters in HTML text, zip comment.
               ``md20 stamp verify FILE`` lists what it finds.
3. Owner-only  a provenance record (UTC time, MD20 version, salted machine/user hash, random id)
               encrypted with the owner's RSA public key (``owner_pub.pem`` shipped in the package).
               Only the holder of the private key can read it: ``md20 stamp decrypt FILE --key private.pem``.

Honest limits: the source is public, so a determined person can strip the markers.  The stamp is
evidence of origin, not copy protection; licensing terms are what restrict commercial use.
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import html as _html
import json
import platform
import re
import secrets
import time
import zipfile
from functools import lru_cache
from pathlib import Path

OWNER = "HCC Lab, National Kaohsiung University of Science and Technology"
OWNER_SHORT = "HCC Lab, NKUST"
TAG = "HCCLab-MD20"
VISIBLE = f"© {OWNER_SHORT} — MD20. All rights reserved."
# PDB/PDBQT are ASCII formats and OpenMM/Vina/mdtraj open them with the *locale* encoding on Windows (cp950 on a
# Traditional-Chinese machine): a non-ASCII REMARK makes app.PDBFile() raise UnicodeDecodeError.  Keep it 7-bit.
VISIBLE_ASCII = f"(c) {OWNER_SHORT} - MD20. All rights reserved."
# D-128: outputs made under an evaluation-tier licence carry this notice (HTML report footer, figure metadata and a faint
# watermark on figures, PDB REMARK, JSON stamp), in the four languages of the program.
EVAL_NOTICE = ("評估版，不得用於決策", "Evaluation version, not for use in decisions",
               "評価版です。意思決定には使用できません", "평가판입니다. 의사결정에 사용할 수 없습니다")
_PUB = Path(__file__).with_name("owner_pub.pem")
_ZW0, _ZW1, _ZWS = "​", "‌", "⁠"   # zero-width space / non-joiner / word joiner (frame)
_SESSION = secrets.token_hex(6)
_T0 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _version() -> str:
    try:
        from .. import __version__
        return __version__
    except Exception:  # noqa: BLE001
        return "?"


def _machine_hash() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "?"
    raw = f"{platform.node()}|{user}|{platform.system()}|{platform.machine()}"
    return hashlib.sha256(("md20-salt-HCC|" + raw).encode()).hexdigest()[:16]


@lru_cache(maxsize=1)
def provenance_blob() -> str:
    """Encrypted provenance (base64) — computed once per process; '' if no key or no `cryptography`."""
    if not _PUB.is_file():
        return ""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        return ""
    rec = {"o": "HCCLab", "v": _version(), "t": _T0, "m": _machine_hash(), "s": _SESSION,
           "py": platform.python_version(), "os": platform.system()[:3]}
    lic = _license_info()
    if lic:
        rec["lid"] = lic["id"]          # D-125: which licence this output was made under (encrypted, owner-readable)
    payload = json.dumps(rec, separators=(",", ":")).encode()
    key = serialization.load_pem_public_key(_PUB.read_bytes())
    ct = key.encrypt(payload, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=b"md20"))
    return base64.b64encode(ct).decode()


def _license_info() -> dict | None:
    """{"id", "who"} of the valid MD20 licence (D-125), or None.  Never raises: a stamp must not break a write."""
    try:
        from .license import stamp_info
        return stamp_info()
    except Exception:  # noqa: BLE001
        return None


def is_evaluation() -> bool:
    """True while the licence in use is an evaluation-tier licence (D-128).  Never raises."""
    try:
        from .license import stamp_tier
        return stamp_tier() == "evaluation"
    except Exception:  # noqa: BLE001
        return False


def evaluation_notice() -> str:
    """The four-language evaluation notice, or '' when the licence is not an evaluation one."""
    return " / ".join(EVAL_NOTICE) if is_evaluation() else ""


def _ascii(text: str, limit: int) -> str:
    return text.encode("ascii", "replace").decode("ascii").replace("\n", " ")[:limit]


def stamp_record() -> dict:
    """Small dict embedded in JSON outputs (key ``_md20``)."""
    d = {"by": TAG, "c": VISIBLE, "v": _version(), "id": _SESSION}
    blob = provenance_blob()
    if blob:
        d["p"] = blob
    lic = _license_info()
    if lic:
        d["lic"] = {"id": lic["id"], "who": lic["who"]}      # licence id and licensee name only (D-125)
        if is_evaluation():
            d["lic"]["tier"] = "evaluation"
            d["eval"] = " / ".join(EVAL_NOTICE)
    return d


# --------------------------------------------------------------------------- zero-width text mark
def zw_encode(text: str = TAG) -> str:
    bits = "".join(f"{b:08b}" for b in text.encode())
    return _ZWS + "".join(_ZW1 if c == "1" else _ZW0 for c in bits) + _ZWS


def zw_decode(s: str) -> list[str]:
    out = []
    for m in re.finditer(f"{_ZWS}([{_ZW0}{_ZW1}]+){_ZWS}", s):
        bits = "".join("1" if c == _ZW1 else "0" for c in m.group(1))
        try:
            out.append(bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits) - 7, 8)).decode())
        except Exception:  # noqa: BLE001
            continue
    return out


# --------------------------------------------------------------------------- per-format helpers
def pdb_remarks() -> list[str]:
    lines = [f"REMARK 999 {VISIBLE_ASCII}"[:80], f"REMARK 999 GENERATED BY MD20 {_version()} ({TAG})"[:80]]
    lic = _license_info()
    if lic:                                        # plain, 7-bit: which licence made this file (D-128)
        lines.append(f"REMARK 999 LICENCE ID {_ascii(lic['id'], 32)}"[:80])
        lines.append(f"REMARK 999 LICENSEE {_ascii(lic['who'], 60)}"[:80])
        if is_evaluation():
            lines.append("REMARK 999 EVALUATION VERSION - NOT FOR USE IN DECISIONS")
    blob = provenance_blob()
    for i in range(0, len(blob), 66):
        lines.append(f"REMARK 999 P {blob[i:i + 66]}")
    return lines


def stamp_pdb_file(path: Path | str) -> None:
    """Prepend REMARK 999 lines (idempotent).  Works for PDB and PDBQT; OpenMM/mdtraj/Vina ignore REMARKs."""
    p = Path(path)
    if not p.is_file():
        return
    text = p.read_text(encoding="utf-8", errors="ignore")
    if TAG in text[:2000]:
        return
    p.write_text("\n".join(pdb_remarks()) + "\n" + text, encoding="utf-8")


def stamp_rdkit_mol(mol) -> None:
    mol.SetProp("MD20_COPYRIGHT", VISIBLE)
    blob = provenance_blob()
    mol.SetProp("MD20_PROVENANCE", f"{TAG}:{blob}" if blob else TAG)


def figure_metadata(fmt: str) -> dict:
    blob = provenance_blob()
    lic = _license_info()
    note = evaluation_notice()
    if fmt == "png":
        md = {"Copyright": VISIBLE, "Software": f"MD20 {_version()}", "Author": OWNER_SHORT, "Comment": TAG}
        if blob:
            md["md20:p"] = blob
        if lic:
            md["md20:lic"] = lic["id"]
        if note:
            md["Disclaimer"] = note
        return md
    if fmt == "svg":
        md = {"Rights": VISIBLE, "Creator": f"MD20 {_version()} ({TAG})", "Description": blob or TAG}
        if lic:
            md["Identifier"] = f"md20-license:{lic['id']}"
        if note:
            md["Title"] = note
        return md
    if fmt == "pdf":
        md = {"Author": OWNER_SHORT, "Creator": f"MD20 {_version()}", "Subject": VISIBLE,
              "Keywords": f"{TAG} " + (f"lic:{lic['id']} " if lic else "") + blob}
        if note:
            md["Title"] = note
        return md
    return {}


def watermark_figure(fig) -> None:
    """Faint diagonal notice across a matplotlib figure under an evaluation licence (D-128).  The drawn text is English only:
    the default fonts have no CJK glyphs; the four-language notice is in the file metadata."""
    if not is_evaluation():
        return
    fig.text(0.5, 0.5, EVAL_NOTICE[1].upper(), ha="center", va="center", rotation=25, fontsize=16, color="#b5651d",
             alpha=0.16, transform=fig.transFigure, zorder=1000)


def html_footer() -> str:
    blob = provenance_blob()
    lic = _license_info()
    lic_html = (f" · Licence ID: {_html.escape(lic['id'])} ({_html.escape(lic['who'])})" if lic else "")
    note = evaluation_notice()
    note_html = (f"<div style='margin-top:.4rem;font-weight:600;color:#b5651d'>{_html.escape(note)}</div>" if note else "")
    return (f"<footer style='margin-top:3rem;font-size:.75rem;color:#8a8984'>{VISIBLE}{zw_encode()}{lic_html}{note_html}"
            f"</footer><!-- {TAG} {blob} -->")


def zip_comment() -> bytes:
    lic = _license_info()
    tail = f" lic:{lic['id']}" if lic else ""
    return f"{VISIBLE} {TAG} {provenance_blob()}{tail}".encode()[:65000]


# --------------------------------------------------------------------------- verification
_LIC_PATTERNS = (re.compile(r'"lic":\s*\{[^{}]*?"id":\s*"([0-9a-f]{16})"'),        # JSON _md20
                 re.compile(r"Licence ID: ([0-9a-f]{16})"),                              # HTML footer
                 re.compile(r"REMARK 999 LICENCE ID ([0-9a-f]{16})"),                    # PDB / PDBQT
                 re.compile(r"md20-license:([0-9a-f]{16})"),                              # SVG dc:identifier
                 re.compile(r"\blic:([0-9a-f]{16})"))                                    # PDF keywords, zip comment


def _find_license_id(text: str, data: bytes) -> str | None:
    for rx in _LIC_PATTERNS:
        m = rx.search(text)
        if m:
            return m.group(1)
    i = data.find(b"md20:lic\x00")                                                      # PNG tEXt
    if i >= 0:
        m = re.match(rb"[0-9a-f]{16}", data[i + 9:i + 40])
        if m:
            return m.group(0).decode()
    return None


def find_markers(path: Path | str) -> dict:
    """Which stamp layers are present in a file.  Returns {"visible":bool, "hidden":[...], "blob": str|None}."""
    p = Path(path)
    data = p.read_bytes()
    text = data.decode("utf-8", errors="ignore")
    found = {"file": str(p), "visible": OWNER_SHORT in text or "HCC Lab" in text, "hidden": [], "blob": None,
             "license_id": _find_license_id(text, data), "evaluation": EVAL_NOTICE[1] in text or EVAL_NOTICE[0] in text
             or "EVALUATION VERSION" in text}
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as zf:
            c = zf.comment.decode(errors="ignore")
        if TAG in c:
            found["hidden"].append("zip comment")
            found["visible"] = found["visible"] or OWNER_SHORT in c
            m = re.search(rf"{TAG} (\S+)", c)
            found["blob"] = m.group(1) if m else None
        return found
    if TAG in text:
        found["hidden"].append("tag")
    if "REMARK 999 P " in text:
        found["hidden"].append("PDB REMARK 999")
        found["blob"] = "".join(l[13:].strip() for l in text.splitlines() if l.startswith("REMARK 999 P "))
    # the stamp holds one nested object (``lic``, D-125), and json.dumps(sort_keys=True) may put it before "p"
    m = re.search(r'"_md20":\s*\{(?:[^{}]|\{[^{}]*\})*?"p":\s*"([A-Za-z0-9+/=]+)"', text)
    if m:
        found["hidden"].append("JSON _md20")
        found["blob"] = found["blob"] or m.group(1)
    if "MD20_PROVENANCE" in text:
        found["hidden"].append("SDF property")
        m = re.search(rf"{TAG}:([A-Za-z0-9+/=]+)", text)
        found["blob"] = found["blob"] or (m.group(1) if m else None)
    if zw_decode(text):
        found["hidden"].append("zero-width text: " + ",".join(zw_decode(text)))
        m = re.search(rf"<!-- {TAG} ([A-Za-z0-9+/=]+) -->", text)
        found["blob"] = found["blob"] or (m.group(1) if m else None)
    if p.suffix.lower() == ".png":
        for key in (b"md20:p", b"Comment"):
            i = data.find(key + b"\x00")
            if i >= 0:
                found["hidden"].append(f"PNG tEXt {key.decode()}")
                if key == b"md20:p":
                    j = i + len(key) + 1
                    blob = re.match(rb"[A-Za-z0-9+/=]+", data[j:j + 800])
                    found["blob"] = blob.group(0).decode() if blob else None
    if p.suffix.lower() == ".svg" and "<dc:description>" in text:
        m = re.search(r"<dc:description>([A-Za-z0-9+/=]{40,})</dc:description>", text)
        if m:
            found["hidden"].append("SVG metadata")
            found["blob"] = found["blob"] or m.group(1)
    return found


def decrypt_blob(blob: str, private_key_pem: Path | str, password: bytes | None = None) -> dict:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key = serialization.load_pem_private_key(Path(private_key_pem).read_bytes(), password=password)
    pt = key.decrypt(base64.b64decode(blob), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=b"md20"))
    return json.loads(pt)
