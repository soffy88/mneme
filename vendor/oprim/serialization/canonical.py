"""RFC 8785 JSON Canonicalization Scheme (JCS)."""

from __future__ import annotations

import json
import math


def canonical_json(
    obj: dict | list | str | int | float | bool | None,
) -> str:
    """RFC 8785 JSON Canonicalization Scheme (JCS).

    Produces a deterministic JSON string suitable for hashing.

    Rules (subset of RFC 8785):
    - UTF-8 encoding (always)
    - No whitespace between tokens
    - Object keys sorted lexicographically (UTF-16 code unit order per RFC 8785 §3.2.3)
    - Numbers: integers as integers, finite floats as shortest round-trip
    - String escaping: minimal (only required by JSON spec)

    Reference: RFC 8785 (2020).
    https://datatracker.ietf.org/doc/html/rfc8785

    Parameters
    ----------
    obj : dict, list, str, int, float, bool, or None
        JSON-serializable Python object. Floats must be finite.

    Returns
    -------
    str
        Deterministic UTF-8 canonical JSON string.

    Raises
    ------
    TypeError
        If object contains unsupported types or non-str dict keys.
    ValueError
        If object contains NaN/Inf floats.
    """
    return _encode(obj)


def _encode(obj) -> str:
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise ValueError(
                f"Float value {obj!r} is not JSON-serializable (RFC 8785 §3.2.2.3 forbids NaN/Inf)"
            )
        if obj == 0.0:
            return "0"
        if obj == int(obj) and abs(obj) < 2**53:
            return str(int(obj))
        return repr(obj)
    if isinstance(obj, str):
        return json.dumps(obj, ensure_ascii=False)
    if isinstance(obj, dict):
        for k in obj:
            if not isinstance(k, str):
                raise TypeError(f"dict key must be str (RFC 8785), got {type(k).__name__}")
        pairs = sorted(obj.items(), key=lambda kv: kv[0].encode("utf-16-be"))
        return (
            "{"
            + ",".join(
                json.dumps(k, ensure_ascii=False) + ":" + _encode(v) for k, v in pairs
            )
            + "}"
        )
    if isinstance(obj, list):
        return "[" + ",".join(_encode(x) for x in obj) + "]"
    raise TypeError(f"Type {type(obj).__name__} is not JSON-serializable (RFC 8785)")
