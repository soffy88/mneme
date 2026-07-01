"""Ed25519 digital signatures — pure Python stdlib implementation (RFC 8032 §5.1).

Phase 3 additions (v2.1.0): PEM key I/O utilities + simplified wrappers
(generate_keypair / sign / verify) for Helivex GOLD signing infrastructure.
"""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)

_GY = 4 * pow(5, _P - 2, _P) % _P
_GX: int
_GX_SQ = (_GY * _GY - 1) * pow(_D * _GY * _GY + 1, _P - 2, _P) % _P
_GX = pow(_GX_SQ, (_P + 3) // 8, _P)
if _GX * _GX % _P != _GX_SQ:
    _GX = _GX * _SQRT_M1 % _P
if _GX % 2 != 0:
    _GX = _P - _GX
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _point_add(P: tuple, Q: tuple) -> tuple:
    A = (P[1] - P[0]) * (Q[1] - Q[0]) % _P
    B = (P[1] + P[0]) * (Q[1] + Q[0]) % _P
    C = 2 * P[3] * Q[3] * _D % _P
    D = 2 * P[2] * Q[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return E * F % _P, G * H % _P, F * G % _P, E * H % _P


def _point_mul(k: int, P: tuple) -> tuple:
    Q = (0, 1, 1, 0)
    while k > 0:
        if k & 1:
            Q = _point_add(Q, P)
        P = _point_add(P, P)
        k >>= 1
    return Q


def _encode_point(P: tuple) -> bytes:
    zinv = pow(P[2], _P - 2, _P)
    x = P[0] * zinv % _P
    y = P[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decode_point(s: bytes) -> tuple | None:
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= ~(1 << 255)
    if y >= _P:
        return None
    y2 = y * y % _P
    x2 = (y2 - 1) * pow(_D * y2 + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if sign else (0, y, 1, 0)
    x = pow(x2, (_P + 3) // 8, _P)
    if x * x % _P != x2:
        x = x * _SQRT_M1 % _P
    if x * x % _P != x2:
        return None
    if bool(x & 1) != bool(sign):
        x = _P - x
    return x, y, 1, x * y % _P


def _expand_secret(seed: bytes) -> tuple[int, bytes]:
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def _dom2(context: bytes | None) -> bytes:
    if context is None:
        return b""
    if len(context) > 255:
        raise ValueError("context must be at most 255 bytes")
    return b"SigEd25519 no Ed25519 collisions\x00" + bytes([len(context)]) + context


def ed25519_keypair_generate(seed: bytes | None = None) -> dict[str, bytes]:
    """Generate an Ed25519 keypair from a 32-byte seed (RFC 8032 §5.1.5).

    Parameters
    ----------
    seed : bytes or None
        32-byte seed for deterministic generation. None → cryptographically
        random seed via :func:`secrets.token_bytes`.

    Returns
    -------
    dict[str, bytes]
        ``{'private_key': <32-byte seed>, 'public_key': <32-byte compressed point>}``

    Raises
    ------
    ValueError
        If *seed* is provided but not exactly 32 bytes.
    """
    if seed is None:
        seed = secrets.token_bytes(32)
    elif len(seed) != 32:
        raise ValueError(f"seed must be exactly 32 bytes, got {len(seed)}")
    a, _ = _expand_secret(seed)
    public_key = _encode_point(_point_mul(a, _G))
    return {"private_key": seed, "public_key": public_key}


def ed25519_sign(
    private_key: bytes,
    message: bytes | str,
    *,
    context: bytes | None = None,
) -> bytes:
    """Sign *message* with an Ed25519 private key (RFC 8032 §5.1.6).

    Parameters
    ----------
    private_key : bytes
        32-byte seed (the ``'private_key'`` value from :func:`ed25519_keypair_generate`).
    message : bytes or str
        Message to sign. str is UTF-8 encoded before signing.
    context : bytes or None
        Optional context string (≤255 bytes). When provided, DOM2 prefix is
        prepended per RFC 8032 §5.1 contextual EdDSA.

    Returns
    -------
    bytes
        64-byte signature ``R || s``.

    Raises
    ------
    ValueError
        If *private_key* is not exactly 32 bytes, or *context* exceeds 255 bytes.
    """
    if len(private_key) != 32:
        raise ValueError(f"private_key must be exactly 32 bytes, got {len(private_key)}")
    if isinstance(message, str):
        message = message.encode("utf-8")
    dom = _dom2(context)
    a, prefix = _expand_secret(private_key)
    A = _encode_point(_point_mul(a, _G))
    r = int.from_bytes(hashlib.sha512(dom + prefix + message).digest(), "little") % _L
    R_bytes = _encode_point(_point_mul(r, _G))
    k = int.from_bytes(hashlib.sha512(dom + R_bytes + A + message).digest(), "little") % _L
    s = (r + k * a) % _L
    return R_bytes + s.to_bytes(32, "little")


def ed25519_verify(
    public_key: bytes,
    message: bytes | str,
    signature: bytes,
    *,
    context: bytes | None = None,
) -> bool:
    """Verify an Ed25519 signature (RFC 8032 §5.1.7).

    Parameters
    ----------
    public_key : bytes
        32-byte compressed Edwards point.
    message : bytes or str
        Message that was signed. str is UTF-8 encoded.
    signature : bytes
        64-byte signature ``R || s``.
    context : bytes or None
        Must match the context used during signing.

    Returns
    -------
    bool
        True if the signature is valid, False otherwise (never raises on bad input).
    """
    try:
        if isinstance(message, str):
            message = message.encode("utf-8")
        if len(signature) != 64 or len(public_key) != 32:
            return False
        dom = _dom2(context)
        R = _decode_point(signature[:32])
        A = _decode_point(public_key)
        if R is None or A is None:
            return False
        s = int.from_bytes(signature[32:], "little")
        if s >= _L:
            return False
        k = (
            int.from_bytes(
                hashlib.sha512(dom + signature[:32] + public_key + message).digest(),
                "little",
            )
            % _L
        )
        lhs = _encode_point(_point_mul(8 * s, _G))
        rhs = _encode_point(_point_add(_point_mul(8, R), _point_mul(8 * k, A)))
        return lhs == rhs
    except Exception:
        return False


# ── Phase 3 v2.1.0: simplified wrappers + PEM key I/O ────────────────────────


def generate_keypair() -> tuple[bytes, bytes]:
    """Generate a random Ed25519 keypair.

    Returns
    -------
    (private_key, public_key) — 32 bytes each
    """
    kp = ed25519_keypair_generate()
    return kp["private_key"], kp["public_key"]


def sign(private_key: bytes, message: bytes) -> bytes:
    """Sign *message* with Ed25519 private key. Returns 64-byte signature."""
    return ed25519_sign(private_key, message)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Verify Ed25519 signature. Returns True if valid, False otherwise."""
    return ed25519_verify(public_key, message, signature)


def save_keypair_pem(
    private_key: bytes,
    public_key: bytes,
    key_dir: Path,
    service_name: str,
) -> None:
    """Write private + public key PEM files.

    Files written:
        {key_dir}/{service_name}.private.pem  — permissions 0600
        {key_dir}/{service_name}.public.pem   — permissions 0644
    """
    key_dir = Path(key_dir)
    key_dir.mkdir(parents=True, exist_ok=True)

    priv_path = key_dir / f"{service_name}.private.pem"
    pub_path = key_dir / f"{service_name}.public.pem"

    priv_path.write_text(
        f"-----BEGIN ED25519 PRIVATE KEY-----\n"
        f"{private_key.hex()}\n"
        f"-----END ED25519 PRIVATE KEY-----\n"
    )
    priv_path.chmod(0o600)

    pub_path.write_text(
        f"-----BEGIN ED25519 PUBLIC KEY-----\n"
        f"{public_key.hex()}\n"
        f"-----END ED25519 PUBLIC KEY-----\n"
    )
    pub_path.chmod(0o644)


def _parse_pem_text(text: str) -> bytes:
    hex_data = "".join(l for l in text.strip().splitlines() if not l.startswith("---"))
    return bytes.fromhex(hex_data)


def load_private_key_pem(path: Path | None = None, *, text: str | None = None) -> bytes:
    """Load Ed25519 private key from PEM file or PEM string. Returns 32 bytes."""
    if text is not None:
        return _parse_pem_text(text)
    return _parse_pem_text(Path(path).read_text())


def load_public_key_pem(path: Path | None = None, *, text: str | None = None) -> bytes:
    """Load Ed25519 public key from PEM file or PEM string. Returns 32 bytes."""
    if text is not None:
        return _parse_pem_text(text)
    return _parse_pem_text(Path(path).read_text())
