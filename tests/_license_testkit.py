"""Test-only helpers that sign licences (D-127).

The product (`md20/`) only verifies licences; issuing lives in the owner's private repository.  The tests still need
licences to verify, so this file holds the smallest possible signer.  It is not part of the package (tests are not
shipped), it only ever signs with a throw-away key made by the fixtures, and its format must stay identical to
docs/specs/licensing.md and tests/data/license_vector_v1.json (test_license_vector.py checks that against the vector that
the signing repository publishes).
"""
import base64
import secrets
import time

from md20.util import license as L

ISSUER = "HCC Lab, NKUST"


def keygen_pair(bits: int = 2048):
    """(private key object, public key PEM bytes) for a throw-away key."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    return key, key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def pss_for_signing():
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    return padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256()


def make_payload(licensee: str, *, expires: str | None = None, days: int | None = None, machines=(), scope: str = "use",
                 note: str = "", version: int | None = None, **v2) -> dict:
    """A payload.  v1 (the nine fields) unless a v2 field is given (tier, features, org, seats, max_version, issuer_key) or
    ``version=2``.  ``issuer_key="auto"`` is replaced by the signing key's fingerprint in ``sign_payload``."""
    import datetime as dt
    if days is not None:
        expires = (dt.date.today() + dt.timedelta(days=int(days))).isoformat()
    mach = sorted({L.normalize_machine(m) for m in (machines or ()) if str(m).strip()})
    if scope not in L.SCOPES or (scope == "all" and mach):
        raise ValueError("bad scope / machines combination")
    unknown = set(v2) - {"tier", "features", "org", "seats", "max_version", "issuer_key"}
    if unknown:
        raise TypeError(f"unknown v2 fields {unknown}")
    use_v2 = bool(v2) or version == 2
    p = {"schema": L.SCHEMA_V2 if use_v2 else L.SCHEMA, "id": secrets.token_hex(8), "licensee": licensee,
         "issued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "expires": expires or None, "machines": mach, "scope": scope, "note": note, "issuer": ISSUER}
    p.update(v2)
    return p


def public_pem_of(private_key) -> bytes:
    from cryptography.hazmat.primitives import serialization
    return private_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def sign_payload(payload: dict, private_key) -> dict:
    """Sign under the prefix of the payload's own schema (v1 or v2)."""
    if payload.get("issuer_key") == "auto":
        payload = {**payload, "issuer_key": L.key_fingerprint(public_pem_of(private_key))}
    domain = L.DOMAIN_V2 if payload.get("schema") == L.SCHEMA_V2 else L.DOMAIN
    pad, algo = pss_for_signing()
    sig = private_key.sign(domain + L.canonical(payload), pad, algo)
    return {"payload": payload, "sig": base64.b64encode(sig).decode("ascii")}


def sign_revocations(ids, private_key, issued_at: str = "2026-11-07T12:00:00Z") -> dict:
    """A signed revocation list {payload: {schema, issued_at, ids}, sig} (prefix md20-revocations-v1)."""
    payload = {"schema": L.REV_SCHEMA, "issued_at": issued_at, "ids": sorted(ids)}
    pad, algo = pss_for_signing()
    return {"payload": payload, "sig": base64.b64encode(private_key.sign(L.REV_DOMAIN + L.canonical(payload), pad, algo)).decode("ascii")}


def pem_bytes(private_key, password: bytes | None = None) -> bytes:
    from cryptography.hazmat.primitives import serialization
    enc = serialization.BestAvailableEncryption(password) if password else serialization.NoEncryption()
    return private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc)


def stamp_keygen(out_dir):
    """Key pair files for the provenance-stamp tests (OAEP encryption to the owner key)."""
    from pathlib import Path
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    key, pub_pem = keygen_pair(3072)
    priv, pub = out / "owner_key.pem", out / "owner_pub.pem"
    priv.write_bytes(pem_bytes(key)); pub.write_bytes(pub_pem)
    return priv, pub
